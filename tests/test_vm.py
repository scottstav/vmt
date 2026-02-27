"""Tests for vmt.vm — VM lifecycle management via libvirt."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from vmt.vm import generate_domain_xml, _vm_dir, VMManager


# ---------------------------------------------------------------------------
# generate_domain_xml
# ---------------------------------------------------------------------------


class TestGenerateDomainXml:
    """Tests for generate_domain_xml()."""

    def _parse(self, **kwargs) -> ET.Element:
        defaults = dict(
            name="testvm",
            memory_mb=2048,
            cpus=2,
            disk_path="/var/lib/vmt/disk.qcow2",
            cloud_init_iso="/var/lib/vmt/seed.iso",
        )
        defaults.update(kwargs)
        xml_str = generate_domain_xml(**defaults)
        return ET.fromstring(xml_str)

    def test_valid_xml(self):
        """Output should be parseable XML."""
        xml_str = generate_domain_xml(
            name="testvm",
            memory_mb=2048,
            cpus=2,
            disk_path="/disk.qcow2",
            cloud_init_iso="/seed.iso",
        )
        root = ET.fromstring(xml_str)
        assert root.tag == "domain"

    def test_domain_name_prefix(self):
        """Domain name should be vmt-{name}."""
        root = self._parse(name="myvm")
        assert root.find("name").text == "vmt-myvm"

    def test_kvm_type(self):
        """Domain type should be kvm."""
        root = self._parse()
        assert root.get("type") == "kvm"

    def test_memory_in_kib(self):
        """Memory should be in KiB (memory_mb * 1024)."""
        root = self._parse(memory_mb=4096)
        mem = root.find("memory")
        assert mem.text == str(4096 * 1024)
        assert mem.get("unit") == "KiB"

    def test_vcpu_count(self):
        """vcpu element should match cpus parameter."""
        root = self._parse(cpus=4)
        assert root.find("vcpu").text == "4"

    def test_os_type_hvm(self):
        """OS type should be hvm."""
        root = self._parse()
        os_type = root.find("os/type")
        assert os_type.text == "hvm"

    def test_os_machine_q35(self):
        """Machine type should be q35."""
        root = self._parse()
        os_type = root.find("os/type")
        assert os_type.get("machine") == "q35"

    def test_boot_from_hd(self):
        """Boot device should be hd."""
        root = self._parse()
        boot = root.find("os/boot")
        assert boot.get("dev") == "hd"

    def test_features_acpi_apic(self):
        """Features should include acpi and apic."""
        root = self._parse()
        features = root.find("features")
        assert features.find("acpi") is not None
        assert features.find("apic") is not None

    def test_virtio_disk(self):
        """Should have a virtio disk at vda."""
        root = self._parse(disk_path="/my/disk.qcow2")
        devices = root.find("devices")
        disks = devices.findall("disk")
        virtio_disk = None
        for d in disks:
            target = d.find("target")
            if target is not None and target.get("dev") == "vda":
                virtio_disk = d
                break
        assert virtio_disk is not None
        assert virtio_disk.find("target").get("bus") == "virtio"
        assert virtio_disk.find("source").get("file") == "/my/disk.qcow2"
        assert virtio_disk.find("driver").get("type") == "qcow2"

    def test_sata_cdrom(self):
        """Should have a SATA cdrom for cloud-init ISO (readonly)."""
        root = self._parse(cloud_init_iso="/my/seed.iso")
        devices = root.find("devices")
        disks = devices.findall("disk")
        cdrom = None
        for d in disks:
            if d.get("device") == "cdrom":
                cdrom = d
                break
        assert cdrom is not None
        assert cdrom.find("source").get("file") == "/my/seed.iso"
        assert cdrom.find("target").get("bus") == "sata"
        assert cdrom.find("readonly") is not None

    def test_spice_graphics(self):
        """Should have SPICE graphics with autoport."""
        root = self._parse()
        devices = root.find("devices")
        graphics = devices.find("graphics")
        assert graphics is not None
        assert graphics.get("type") == "spice"
        assert graphics.get("autoport") == "yes"
        assert graphics.get("listen") == "127.0.0.1"

    def test_virtio_network(self):
        """Should have a virtio network interface on 'default'."""
        root = self._parse()
        devices = root.find("devices")
        iface = devices.find("interface")
        assert iface is not None
        assert iface.get("type") == "network"
        assert iface.find("source").get("network") == "default"
        assert iface.find("model").get("type") == "virtio"

    def test_serial_console(self):
        """Should have a serial console."""
        root = self._parse()
        devices = root.find("devices")
        serial = devices.find("serial")
        assert serial is not None

    def test_spicevmc_channel(self):
        """Should have a spicevmc channel."""
        root = self._parse()
        devices = root.find("devices")
        channels = devices.findall("channel")
        spice_channels = [
            c for c in channels if c.get("type") == "spicevmc"
        ]
        assert len(spice_channels) >= 1


# ---------------------------------------------------------------------------
# _vm_dir
# ---------------------------------------------------------------------------


class TestVmDir:
    """Tests for _vm_dir()."""

    @patch("vmt.vm.Path.home")
    def test_path_contains_vmt_and_name(self, mock_home, tmp_path):
        mock_home.return_value = tmp_path
        result = _vm_dir("myvm")
        assert "vmt" in str(result)
        assert "myvm" in str(result)

    @patch("vmt.vm.Path.home")
    def test_creates_directory(self, mock_home, tmp_path):
        mock_home.return_value = tmp_path
        result = _vm_dir("newvm")
        assert result.is_dir()

    @patch("vmt.vm.Path.home")
    def test_path_structure(self, mock_home, tmp_path):
        mock_home.return_value = tmp_path
        result = _vm_dir("testvm")
        expected = tmp_path / ".cache" / "vmt" / "vms" / "testvm"
        assert result == expected


# ---------------------------------------------------------------------------
# _create_overlay_disk
# ---------------------------------------------------------------------------


class TestCreateOverlayDisk:
    """Tests for VMManager._create_overlay_disk()."""

    @patch("vmt.vm.subprocess.run")
    @patch("vmt.vm.libvirt.open", return_value=MagicMock())
    def test_calls_qemu_img(self, mock_libvirt_open, mock_run):
        mgr = VMManager()
        base = Path("/images/base.qcow2")
        overlay = Path("/vms/test/disk.qcow2")
        mgr._create_overlay_disk(base, overlay)

        mock_run.assert_called_once_with(
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
        mgr.close()


# ---------------------------------------------------------------------------
# VMManager constructor
# ---------------------------------------------------------------------------


class TestVMManagerConstructor:
    """Tests for VMManager.__init__()."""

    @patch("vmt.vm.libvirt.open", return_value=MagicMock())
    def test_connects_to_qemu_system(self, mock_open):
        mgr = VMManager()
        mock_open.assert_called_once_with("qemu:///system")
        mgr.close()

    @patch("vmt.vm.libvirt.open", return_value=MagicMock())
    def test_default_manifest_dirs(self, mock_open):
        mgr = VMManager()
        # Should have at least one directory in manifest_dirs
        assert len(mgr.manifest_dirs) >= 1
        # The default should point to the package's manifests dir
        assert mgr.manifest_dirs[0].name == "manifests"
        mgr.close()

    @patch("vmt.vm.libvirt.open", return_value=MagicMock())
    def test_custom_manifest_dirs(self, mock_open, tmp_path):
        dirs = [tmp_path / "custom"]
        mgr = VMManager(manifest_dirs=dirs)
        assert mgr.manifest_dirs == dirs
        mgr.close()

    @patch("vmt.vm.libvirt.open", return_value=MagicMock())
    def test_close_closes_connection(self, mock_open):
        mock_conn = MagicMock()
        mock_open.return_value = mock_conn
        mgr = VMManager()
        mgr.close()
        mock_conn.close.assert_called_once()
