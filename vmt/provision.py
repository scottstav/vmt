"""Cloud-init generation for VM provisioning."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml


def _is_arch_manifest(manifest: dict) -> bool:
    """Return True if the manifest targets Arch Linux."""
    image = manifest.get("vm", {}).get("image", "")
    return "arch" in image.lower() or "archlinux" in image.lower()


def generate_user_data(manifest: dict, ssh_pubkey: str) -> str:
    """Generate cloud-init user-data YAML from a VM manifest dict.

    Creates a cloud-config that sets up:
    - A user account with SSH key, password, and passwordless sudo
    - Package installation (with pacman-key init for Arch)
    - A Wayland compositor as a systemd user service (headless mode)
    - TTY autologin + .bash_profile compositor launch (DRM/SPICE mode)
    - PipeWire audio started via runcmd
    - ~/.local/bin on PATH
    """
    user = manifest["ssh"]["user"]
    provision = manifest["provision"]
    packages = provision["packages"]
    compositor_cmd = provision["compositor_cmd"]
    env_vars = provision.get("env", {})

    # --- Headless systemd service (WLR_BACKENDS=headless for grim) ----------
    # Build Environment= directives from provision.env, forcing headless
    headless_env = dict(env_vars)
    headless_env["WLR_BACKENDS"] = "headless"
    env_lines = "\n".join(
        f'Environment="{k}={v}"' for k, v in headless_env.items()
    )
    service_content = (
        "[Unit]\n"
        "Description=Test Compositor\n"
        "After=pipewire.service\n"
        "\n"
        "[Service]\n"
        f"{env_lines}\n"
        f"ExecStart={compositor_cmd}\n"
        "Restart=on-failure\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )

    # --- TTY autologin for SPICE/DRM interactive use ------------------------
    autologin_content = (
        "[Service]\n"
        "ExecStart=\n"
        f"ExecStart=-/sbin/agetty --autologin {user} --noclear %I $TERM\n"
    )

    # .bash_profile launches compositor on tty1 (DRM mode)
    bash_profile_content = (
        f'[ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] && exec {compositor_cmd}\n'
    )

    # --- bootcmd ------------------------------------------------------------
    bootcmd: list = [
        "systemctl mask --now systemd-time-wait-sync.service",
    ]
    # Arch cloud images have empty keyrings; init them before package install
    if _is_arch_manifest(manifest):
        bootcmd.append("pacman-key --init && pacman-key --populate archlinux")

    cloud_config: dict = {
        # bootcmd runs early, before services block on time-sync.
        "bootcmd": bootcmd,
        "users": [
            {
                "name": user,
                "ssh_authorized_keys": [ssh_pubkey],
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "groups": ["video", "audio"],
                "shell": "/bin/bash",
                "lock_passwd": False,
                "plain_text_passwd": "vmt",
            },
        ],
        "chpasswd": {"expire": False},
        "ssh_pwauth": True,
        "package_update": True,
        "packages": list(packages),
        # write_files uses defer: true so entries are written during the
        # final stage, after the user has been created.
        "write_files": [
            {
                "path": f"/home/{user}/.config/systemd/user/test-compositor.service",
                "owner": f"{user}:{user}",
                "defer": True,
                "content": service_content,
            },
            {
                "path": "/etc/systemd/system/getty@tty1.service.d/autologin.conf",
                "content": autologin_content,
            },
            {
                "path": f"/home/{user}/.bash_profile",
                "owner": f"{user}:{user}",
                "defer": True,
                "content": bash_profile_content,
            },
            {
                "path": f"/home/{user}/.bashrc",
                "owner": f"{user}:{user}",
                "defer": True,
                "append": True,
                "content": 'export PATH="$HOME/.local/bin:$PATH"\n',
            },
        ],
        "runcmd": [
            # Ensure sshd is running (some cloud images don't enable it)
            "systemctl enable --now sshd || systemctl enable --now ssh || true",
            f"loginctl enable-linger {user}",
            # Start user services via machinectl which sets up the full
            # user session environment (XDG_RUNTIME_DIR, DBUS, etc.)
            f"machinectl shell {user}@ /bin/bash -c "
            f"'systemctl --user start pipewire wireplumber test-compositor' "
            "|| true",
        ],
    }

    yaml_body = yaml.dump(cloud_config, default_flow_style=False, sort_keys=False)
    return f"#cloud-config\n{yaml_body}"


def generate_meta_data(vm_name: str) -> str:
    """Generate cloud-init meta-data YAML.

    Returns YAML with instance-id and local-hostname.
    """
    meta: dict = {
        "instance-id": f"vmt-{vm_name}",
        "local-hostname": vm_name,
    }
    return yaml.dump(meta, default_flow_style=False, sort_keys=False)


def create_cloud_init_iso(
    user_data: str, meta_data: str, output_path: Path
) -> None:
    """Create a cloud-init NoCloud ISO using cloud-localds.

    Writes user-data and meta-data to temporary files, invokes
    cloud-localds to build the ISO at output_path, then cleans up.
    """
    ud_file = None
    md_file = None
    try:
        ud_file = tempfile.NamedTemporaryFile(
            mode="w", suffix="-user-data", delete=False
        )
        ud_file.write(user_data)
        ud_file.close()

        md_file = tempfile.NamedTemporaryFile(
            mode="w", suffix="-meta-data", delete=False
        )
        md_file.write(meta_data)
        md_file.close()

        subprocess.run(
            ["cloud-localds", str(output_path), ud_file.name, md_file.name],
            check=True,
            capture_output=True,
        )
    finally:
        for f in (ud_file, md_file):
            if f is not None:
                Path(f.name).unlink(missing_ok=True)
