"""Tests for vmt.provision — cloud-init generation."""

import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from vmt.provision import (
    create_cloud_init_iso,
    generate_meta_data,
    generate_user_data,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MANIFEST = {
    "ssh": {"user": "vmtuser"},
    "provision": {
        "packages": ["weston", "mesa-utils", "xdg-utils"],
        "compositor_cmd": "/usr/bin/weston --backend=drm",
        "env": {
            "WLR_BACKENDS": "drm",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        },
    },
}

SAMPLE_SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey test@host"


@pytest.fixture
def manifest():
    return SAMPLE_MANIFEST


@pytest.fixture
def ssh_key():
    return SAMPLE_SSH_KEY


# ---------------------------------------------------------------------------
# generate_user_data
# ---------------------------------------------------------------------------


class TestGenerateUserData:
    def test_starts_with_cloud_config_header(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        assert result.startswith("#cloud-config\n")

    def test_produces_valid_yaml(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        # Strip the #cloud-config header line before parsing
        yaml_body = result.split("\n", 1)[1]
        data = yaml.safe_load(yaml_body)
        assert isinstance(data, dict)

    def test_user_entry(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        users = data["users"]
        # First entry may be "default"; find our user
        user = next(u for u in users if isinstance(u, dict) and u["name"] == "vmtuser")
        assert ssh_key in user["ssh_authorized_keys"]
        assert "sudo" in user
        assert "NOPASSWD" in user["sudo"]

    def test_user_groups(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        user = next(u for u in data["users"] if isinstance(u, dict))
        groups = user["groups"]
        assert "video" in groups
        assert "audio" in groups

    def test_package_update(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        assert data["package_update"] is True

    def test_packages_list(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        assert data["packages"] == ["weston", "mesa-utils", "xdg-utils"]

    def test_compositor_service_in_write_files(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        write_files = data["write_files"]
        service_file = next(
            f
            for f in write_files
            if "test-compositor.service" in f["path"]
        )
        assert service_file["path"] == "/home/vmtuser/.config/systemd/user/test-compositor.service"
        content = service_file["content"]
        assert "ExecStart=/usr/bin/weston --backend=drm" in content
        assert 'Environment="WLR_BACKENDS=drm"' in content
        assert 'Environment="XDG_RUNTIME_DIR=/run/user/1000"' in content

    def test_runcmd_enable_linger(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        runcmd = data["runcmd"]
        linger_cmds = [c for c in runcmd if "loginctl" in str(c) and "enable-linger" in str(c)]
        assert len(linger_cmds) >= 1

    def test_runcmd_starts_pipewire(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        runcmd = data["runcmd"]
        runcmd_str = str(runcmd)
        assert "pipewire" in runcmd_str

    def test_runcmd_starts_compositor(self, manifest, ssh_key):
        result = generate_user_data(manifest, ssh_key)
        data = yaml.safe_load(result.split("\n", 1)[1])
        runcmd = data["runcmd"]
        runcmd_str = str(runcmd)
        assert "test-compositor" in runcmd_str


# ---------------------------------------------------------------------------
# generate_meta_data
# ---------------------------------------------------------------------------


class TestGenerateMetaData:
    def test_produces_valid_yaml(self):
        result = generate_meta_data("myvm")
        data = yaml.safe_load(result)
        assert isinstance(data, dict)

    def test_instance_id(self):
        result = generate_meta_data("myvm")
        data = yaml.safe_load(result)
        assert data["instance-id"] == "vmt-myvm"

    def test_hostname(self):
        result = generate_meta_data("myvm")
        data = yaml.safe_load(result)
        assert data["local-hostname"] == "myvm"


# ---------------------------------------------------------------------------
# create_cloud_init_iso
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("cloud-localds") is None,
    reason="cloud-localds not installed",
)
class TestCreateCloudInitIso:
    def test_creates_iso_file(self):
        user_data = "#cloud-config\npackages: [vim]\n"
        meta_data = "instance-id: test\nlocal-hostname: test\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "seed.iso"
            create_cloud_init_iso(user_data, meta_data, output)
            assert output.exists()
            assert output.stat().st_size > 0
