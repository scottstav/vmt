"""Core VM lifecycle management via libvirt."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from textwrap import dedent

import libvirt

from vmt.connect import SSHClient, get_ssh_pubkey
from vmt.manifest import find_manifest, load_vm_manifest
from vmt.provision import create_cloud_init_iso, generate_meta_data, generate_user_data

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_IMAGES_DIR = Path.home() / ".cache" / "vmt" / "images"


def _vm_dir(name: str) -> Path:
    """Per-VM working directory at ~/.cache/vmt/vms/{name}.

    Creates the directory (and parents) if it doesn't exist.
    """
    d = Path.home() / ".cache" / "vmt" / "vms" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# QEMU access (ACL helpers)
# ---------------------------------------------------------------------------

_QEMU_USER = "libvirt-qemu"


def _grant_qemu_access(path: Path) -> None:
    """Ensure the libvirt-qemu user can reach *path* through every ancestor.

    Uses POSIX ACLs (``setfacl``) to grant the QEMU process user execute
    permission on each directory component that is otherwise too restrictive,
    and read+execute on the final directory itself (so QEMU can open files
    inside it).

    This is necessary when connecting via ``qemu:///system`` because the QEMU
    process runs as the ``libvirt-qemu`` user, which typically cannot traverse
    a user's home directory (mode 700).

    Only directories that lack "other-execute" permission get an ACL entry,
    so we don't touch directories that are already world-traversable.
    """
    path = path.resolve()

    # Walk from root down to *path*, granting execute on each ancestor
    parts: list[Path] = list(reversed(list(path.parents)))  # [/, /home, ...]
    parts.append(path)  # include the target itself

    for p in parts:
        if not p.is_dir():
            continue
        st = p.stat()
        # Check if "other" already has execute permission
        if st.st_mode & 0o001:
            continue
        # Grant user ACL: execute only (for traversal) on ancestors,
        # read+execute on the target itself so QEMU can list files
        perm = "rx" if p == path else "x"
        try:
            subprocess.run(
                ["setfacl", "-m", f"u:{_QEMU_USER}:{perm}", str(p)],
                check=True,
                capture_output=True,
            )
            log.debug("Granted %s ACL u:%s:%s on %s", perm, _QEMU_USER, perm, p)
        except subprocess.CalledProcessError as exc:
            log.warning(
                "setfacl failed on %s: %s (QEMU may not be able to access VM files)",
                p,
                exc.stderr.decode().strip(),
            )


# ---------------------------------------------------------------------------
# Domain XML generation
# ---------------------------------------------------------------------------


def generate_domain_xml(
    name: str,
    memory_mb: int,
    cpus: int,
    disk_path: str,
    cloud_init_iso: str,
) -> str:
    """Generate libvirt domain XML string.

    Domain name is ``vmt-{name}``.  Uses KVM, q35 machine, boots from HD.
    """
    memory_kib = memory_mb * 1024
    return dedent(f"""\
        <domain type='kvm'>
          <name>vmt-{name}</name>
          <memory unit='KiB'>{memory_kib}</memory>
          <vcpu>{cpus}</vcpu>
          <os>
            <type arch='x86_64' machine='q35'>hvm</type>
            <boot dev='hd'/>
          </os>
          <features>
            <acpi/>
            <apic/>
          </features>
          <devices>
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='{disk_path}'/>
              <target dev='vda' bus='virtio'/>
            </disk>
            <disk type='file' device='cdrom'>
              <driver name='qemu' type='raw'/>
              <source file='{cloud_init_iso}'/>
              <target dev='sda' bus='sata'/>
              <readonly/>
            </disk>
            <interface type='network'>
              <source network='default'/>
              <model type='virtio'/>
            </interface>
            <graphics type='spice' autoport='yes' listen='127.0.0.1'/>
            <video>
              <model type='virtio'/>
            </video>
            <channel type='spicevmc'>
              <target type='virtio' name='com.redhat.spice.0'/>
            </channel>
            <serial type='pty'>
              <target port='0'/>
            </serial>
            <console type='pty'>
              <target type='serial' port='0'/>
            </console>
          </devices>
        </domain>
    """)


# ---------------------------------------------------------------------------
# VMManager
# ---------------------------------------------------------------------------


class VMManager:
    """Manages VM lifecycle via libvirt."""

    def __init__(self, manifest_dirs: list[Path] | None = None) -> None:
        self._conn = libvirt.open("qemu:///system")
        if self._conn is None:
            raise RuntimeError("Failed to connect to qemu:///system")

        if manifest_dirs is not None:
            self.manifest_dirs = manifest_dirs
        else:
            # Default: the manifests/ directory next to this package
            pkg_parent = Path(__file__).resolve().parent.parent
            self.manifest_dirs = [pkg_parent / "manifests"]

    def close(self) -> None:
        """Close the libvirt connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── public API ────────────────────────────────────────────────────

    def up(self, name: str) -> dict:
        """Full boot sequence for a VM.

        1. Find and load VM manifest
        2. Download cloud image (skip if cached)
        3. Create copy-on-write overlay disk
        4. Generate cloud-init ISO
        5. Grant QEMU user access to VM files via POSIX ACLs
        6. Define and start libvirt domain
        7. Wait for IP via DHCP leases
        8. Wait for SSH
        9. Return info dict

        Returns:
            dict with keys: name, domain, ip, ssh_user, ssh_port, spice_port
        """
        # 1. Load manifest
        manifest_path = find_manifest(name, self.manifest_dirs)
        manifest = load_vm_manifest(manifest_path)
        vm_cfg = manifest["vm"]
        ssh_cfg = manifest["ssh"]

        vm_name = vm_cfg["name"]
        image_url = vm_cfg["image"]
        memory_mb = vm_cfg["memory"]
        cpus = vm_cfg["cpus"]
        ssh_user = ssh_cfg["user"]
        ssh_port = ssh_cfg.get("port", 22)

        # 2. Download cloud image
        _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        image_filename = image_url.rsplit("/", 1)[-1] if "/" in image_url else image_url
        base_image = _IMAGES_DIR / image_filename
        if not base_image.exists():
            log.info("Downloading cloud image: %s", image_url)
            urllib.request.urlretrieve(image_url, str(base_image))
        else:
            log.info("Using cached image: %s", base_image)

        # 3. Create overlay disk
        workdir = _vm_dir(vm_name)
        overlay = workdir / "disk.qcow2"
        self._create_overlay_disk(base_image, overlay)

        # 4. Generate cloud-init ISO
        ssh_pubkey = get_ssh_pubkey()
        user_data = generate_user_data(manifest, ssh_pubkey)
        meta_data = generate_meta_data(vm_name)
        ci_iso = workdir / "seed.iso"
        create_cloud_init_iso(user_data, meta_data, ci_iso)

        # 5. Grant QEMU user access to VM files via ACLs
        _grant_qemu_access(_IMAGES_DIR)
        _grant_qemu_access(workdir)

        # 6. Define and start domain
        domain_name = f"vmt-{vm_name}"
        self._cleanup_existing_domain(domain_name)

        xml = generate_domain_xml(
            name=vm_name,
            memory_mb=memory_mb,
            cpus=cpus,
            disk_path=str(overlay),
            cloud_init_iso=str(ci_iso),
        )
        dom = self._conn.defineXML(xml)
        dom.create()
        log.info("Domain %s started", domain_name)

        # 7. Wait for IP
        ip = self._wait_for_ip(dom)
        log.info("VM %s got IP: %s", vm_name, ip)

        # 8. Wait for SSH
        ssh = SSHClient(host=ip, user=ssh_user, port=ssh_port)
        ssh.wait_until_ready()
        ssh.close()
        log.info("SSH ready on %s", ip)

        # 9. Return info
        spice_port = self._get_spice_port(dom)
        return {
            "name": vm_name,
            "domain": domain_name,
            "ip": ip,
            "ssh_user": ssh_user,
            "ssh_port": ssh_port,
            "spice_port": spice_port,
        }

    def destroy(self, name: str) -> None:
        """Destroy a VM domain, undefine it, and clean up its working directory."""
        domain_name = f"vmt-{name}"
        self._cleanup_existing_domain(domain_name)

        # Remove working directory
        workdir = _vm_dir(name)
        if workdir.exists():
            shutil.rmtree(workdir)
            log.info("Removed working directory: %s", workdir)

    def get_info(self, name: str) -> dict | None:
        """Get info for a running VM, or None if not found/running."""
        domain_name = f"vmt-{name}"
        try:
            dom = self._conn.lookupByName(domain_name)
        except libvirt.libvirtError:
            return None

        state, _ = dom.state()
        if state != libvirt.VIR_DOMAIN_RUNNING:
            return None

        ip = self._get_ip(dom)
        spice_port = self._get_spice_port(dom)

        # Load manifest to get SSH user/port
        ssh_user = "root"
        ssh_port = 22
        try:
            manifest_path = find_manifest(name, self.manifest_dirs)
            manifest = load_vm_manifest(manifest_path)
            ssh_cfg = manifest.get("ssh", {})
            ssh_user = ssh_cfg.get("user", "root")
            ssh_port = ssh_cfg.get("port", 22)
        except (FileNotFoundError, KeyError):
            pass

        return {
            "name": name,
            "domain": domain_name,
            "ip": ip,
            "ssh_user": ssh_user,
            "ssh_port": ssh_port,
            "spice_port": spice_port,
        }

    def snapshot(self, name: str, snap_name: str) -> None:
        """Create a libvirt snapshot of a VM."""
        domain_name = f"vmt-{name}"
        dom = self._conn.lookupByName(domain_name)
        snap_xml = f"<domainsnapshot><name>{snap_name}</name></domainsnapshot>"
        dom.snapshotCreateXML(snap_xml)
        log.info("Created snapshot '%s' for %s", snap_name, domain_name)

    def restore(self, name: str, snap_name: str) -> None:
        """Revert a VM to a named snapshot."""
        domain_name = f"vmt-{name}"
        dom = self._conn.lookupByName(domain_name)
        snap = dom.snapshotLookupByName(snap_name)
        dom.revertToSnapshot(snap)
        log.info("Reverted %s to snapshot '%s'", domain_name, snap_name)

    # ── internal helpers ──────────────────────────────────────────────

    def _create_overlay_disk(self, base: Path, overlay: Path) -> None:
        """Create a copy-on-write qcow2 overlay backed by base image."""
        subprocess.run(
            [
                "qemu-img", "create",
                "-f", "qcow2",
                "-b", str(base),
                "-F", "qcow2",
                str(overlay),
            ],
            check=True,
            capture_output=True,
        )

    def _wait_for_ip(self, dom, timeout: int = 60) -> str:
        """Poll DHCP leases until an IPv4 address appears."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ip = self._get_ip(dom)
            if ip is not None:
                return ip
            time.sleep(2)
        raise TimeoutError(
            f"No IP address for domain '{dom.name()}' after {timeout}s"
        )

    def _get_ip(self, dom) -> str | None:
        """Get the first IPv4 address from DHCP leases, or None."""
        try:
            ifaces = dom.interfaceAddresses(
                libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE
            )
        except libvirt.libvirtError:
            return None

        for iface_info in ifaces.values():
            for addr in iface_info.get("addrs", []):
                if addr.get("type") == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                    return addr["addr"]
        return None

    def _get_spice_port(self, dom) -> int | None:
        """Parse domain XML to find the SPICE listen port."""
        xml_str = dom.XMLDesc()
        root = ET.fromstring(xml_str)
        graphics = root.find(".//graphics[@type='spice']")
        if graphics is not None:
            port = graphics.get("port")
            if port and port != "-1":
                return int(port)
        return None

    def _cleanup_existing_domain(self, domain_name: str) -> None:
        """Destroy and undefine an existing domain if it exists."""
        try:
            dom = self._conn.lookupByName(domain_name)
        except libvirt.libvirtError:
            return  # Domain doesn't exist

        try:
            state, _ = dom.state()
            if state == libvirt.VIR_DOMAIN_RUNNING:
                dom.destroy()
                log.info("Destroyed running domain: %s", domain_name)
        except libvirt.libvirtError:
            pass

        try:
            dom.undefine()
            log.info("Undefined domain: %s", domain_name)
        except libvirt.libvirtError:
            pass
