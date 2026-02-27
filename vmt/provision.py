"""Cloud-init generation for VM provisioning."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml


def generate_user_data(manifest: dict, ssh_pubkey: str) -> str:
    """Generate cloud-init user-data YAML from a VM manifest dict.

    Creates a cloud-config that sets up:
    - A user account with SSH key and passwordless sudo
    - Package installation
    - A Wayland compositor as a systemd user service
    - PipeWire audio and the compositor started via runcmd
    """
    user = manifest["ssh"]["user"]
    provision = manifest["provision"]
    packages = provision["packages"]
    compositor_cmd = provision["compositor_cmd"]
    env_vars = provision.get("env", {})

    # Build the systemd unit for the compositor
    env_lines = "\n".join(
        f'Environment="{k}={v}"' for k, v in env_vars.items()
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

    cloud_config: dict = {
        "users": [
            {
                "name": user,
                "ssh_authorized_keys": [ssh_pubkey],
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "groups": ["video", "audio"],
                "shell": "/bin/bash",
            },
        ],
        "package_update": True,
        "packages": list(packages),
        "write_files": [
            {
                "path": f"/home/{user}/.config/systemd/user/test-compositor.service",
                "owner": f"{user}:{user}",
                "content": service_content,
            },
        ],
        "runcmd": [
            f"loginctl enable-linger {user}",
            f"su - {user} -c 'systemctl --user start pipewire'",
            f"su - {user} -c 'systemctl --user start wireplumber'",
            f"su - {user} -c 'systemctl --user start test-compositor'",
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
