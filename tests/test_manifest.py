"""Tests for vmt.manifest — VM and test manifest parsing."""

import pytest
from pathlib import Path

from vmt.manifest import load_vm_manifest, load_test_manifest, find_manifest


# ---------------------------------------------------------------------------
# load_vm_manifest
# ---------------------------------------------------------------------------

class TestLoadVmManifest:
    """Tests for load_vm_manifest()."""

    def test_valid_full_manifest(self, tmp_path):
        """All sections and fields present — should load without error."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
name = "arch-sway"
image = "archlinux-2024.01.01.qcow2"
memory = 4096
cpus = 4
disk = 20

[provision]
packages = ["sway", "foot"]
env = { WLR_BACKENDS = "headless" }

[ssh]
user = "root"
port = 2222
""")
        m = load_vm_manifest(p)
        assert m["vm"]["name"] == "arch-sway"
        assert m["vm"]["image"] == "archlinux-2024.01.01.qcow2"
        assert m["vm"]["memory"] == 4096
        assert m["vm"]["cpus"] == 4
        assert m["vm"]["disk"] == 20
        assert m["provision"]["packages"] == ["sway", "foot"]
        assert m["provision"]["env"]["WLR_BACKENDS"] == "headless"
        assert m["ssh"]["user"] == "root"
        assert m["ssh"]["port"] == 2222

    def test_missing_vm_section(self, tmp_path):
        """Missing [vm] section should raise ValueError."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[provision]
packages = []

[ssh]
user = "root"
""")
        with pytest.raises(ValueError, match="vm"):
            load_vm_manifest(p)

    def test_missing_provision_section(self, tmp_path):
        """Missing [provision] section should raise ValueError."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
name = "test"
image = "test.qcow2"

[ssh]
user = "root"
""")
        with pytest.raises(ValueError, match="provision"):
            load_vm_manifest(p)

    def test_missing_ssh_section(self, tmp_path):
        """Missing [ssh] section should raise ValueError."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
name = "test"
image = "test.qcow2"

[provision]
packages = []
""")
        with pytest.raises(ValueError, match="ssh"):
            load_vm_manifest(p)

    def test_missing_name_field(self, tmp_path):
        """Missing vm.name should raise ValueError."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
image = "test.qcow2"

[provision]
packages = []

[ssh]
user = "root"
""")
        with pytest.raises(ValueError, match="name"):
            load_vm_manifest(p)

    def test_missing_image_field(self, tmp_path):
        """Missing vm.image should raise ValueError."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
name = "test"

[provision]
packages = []

[ssh]
user = "root"
""")
        with pytest.raises(ValueError, match="image"):
            load_vm_manifest(p)

    def test_defaults_applied(self, tmp_path):
        """When memory/cpus/disk are omitted, defaults should be filled in."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
name = "minimal"
image = "base.qcow2"

[provision]
packages = []

[ssh]
user = "root"
""")
        m = load_vm_manifest(p)
        assert m["vm"]["memory"] == 2048
        assert m["vm"]["cpus"] == 2
        assert m["vm"]["disk"] == 10

    def test_provision_env_defaults_to_empty(self, tmp_path):
        """If provision.env is missing, it should default to empty dict."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
name = "no-env"
image = "base.qcow2"

[provision]
packages = ["vim"]

[ssh]
user = "root"
""")
        m = load_vm_manifest(p)
        assert m["provision"]["env"] == {}

    def test_partial_defaults_not_overwritten(self, tmp_path):
        """Explicit values should not be overwritten by defaults."""
        p = tmp_path / "vm.toml"
        p.write_text("""\
[vm]
name = "custom"
image = "base.qcow2"
memory = 8192

[provision]
packages = []

[ssh]
user = "root"
""")
        m = load_vm_manifest(p)
        assert m["vm"]["memory"] == 8192
        assert m["vm"]["cpus"] == 2  # default
        assert m["vm"]["disk"] == 10  # default


# ---------------------------------------------------------------------------
# load_test_manifest
# ---------------------------------------------------------------------------

class TestLoadTestManifest:
    """Tests for load_test_manifest()."""

    def test_valid_test_manifest(self, tmp_path):
        """Basic test manifest with [test] and [[scenario]]."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[test]
vm = "arch-sway"

[[scenario]]
name = "launch"
commands = ["myapp &", "sleep 2"]
screenshot = "launch.png"
reference = "references/launch.png"
threshold = 0.95
""")
        m = load_test_manifest(p)
        assert m["test"]["vm"] == "arch-sway"
        assert len(m["scenario"]) == 1
        s = m["scenario"][0]
        assert s["name"] == "launch"
        assert s["commands"] == ["myapp &", "sleep 2"]
        assert s["screenshot"] == "launch.png"
        assert s["reference"] == "references/launch.png"
        assert s["threshold"] == 0.95

    def test_missing_test_section(self, tmp_path):
        """Missing [test] section should raise ValueError."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[[scenario]]
name = "launch"
commands = ["echo hi"]
""")
        with pytest.raises(ValueError, match="test"):
            load_test_manifest(p)

    def test_missing_scenario_section(self, tmp_path):
        """Missing [[scenario]] section should raise ValueError."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[test]
vm = "arch-sway"
""")
        with pytest.raises(ValueError, match="scenario"):
            load_test_manifest(p)

    def test_multiple_scenarios(self, tmp_path):
        """Multiple [[scenario]] entries should all be parsed."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[test]
vm = "arch-sway"

[[scenario]]
name = "startup"
commands = ["myapp &"]

[[scenario]]
name = "resize"
commands = ["swaymsg resize set 800 600"]
screenshot = "resize.png"
reference = "references/resize.png"
threshold = 0.98
""")
        m = load_test_manifest(p)
        assert len(m["scenario"]) == 2
        assert m["scenario"][0]["name"] == "startup"
        assert m["scenario"][1]["name"] == "resize"
        assert m["scenario"][1]["threshold"] == 0.98

    def test_scenario_with_expect_output(self, tmp_path):
        """Scenario with expect_output field."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[test]
vm = "arch-sway"

[[scenario]]
name = "version-check"
commands = ["myapp --version"]
expect_output = "myapp 1.0.0"
""")
        m = load_test_manifest(p)
        assert m["scenario"][0]["expect_output"] == "myapp 1.0.0"

    def test_install_section(self, tmp_path):
        """Test manifest with [install] section."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[test]
vm = "arch-sway"

[install]
commands = ["make install"]

[[scenario]]
name = "basic"
commands = ["echo hello"]
""")
        m = load_test_manifest(p)
        assert m["install"]["commands"] == ["make install"]

    def test_distro_specific_install(self, tmp_path):
        """Test manifest with [install.<distro>] sections."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[test]
vm = "arch-sway"

[install]
commands = ["make install"]

[install.arch]
commands = ["pacman -S --noconfirm myapp"]

[install.ubuntu]
commands = ["apt-get install -y myapp"]

[[scenario]]
name = "basic"
commands = ["echo hello"]
""")
        m = load_test_manifest(p)
        assert m["install"]["arch"]["commands"] == ["pacman -S --noconfirm myapp"]
        assert m["install"]["ubuntu"]["commands"] == ["apt-get install -y myapp"]
        assert m["install"]["commands"] == ["make install"]

    def test_screenshot_without_reference(self, tmp_path):
        """Scenario with screenshot but no reference (for initial capture)."""
        p = tmp_path / "test.toml"
        p.write_text("""\
[test]
vm = "arch-sway"

[[scenario]]
name = "capture"
commands = ["myapp &", "sleep 1"]
screenshot = "initial.png"
""")
        m = load_test_manifest(p)
        s = m["scenario"][0]
        assert s["screenshot"] == "initial.png"
        assert "reference" not in s


# ---------------------------------------------------------------------------
# find_manifest
# ---------------------------------------------------------------------------

class TestFindManifest:
    """Tests for find_manifest()."""

    def test_find_in_single_directory(self, tmp_path):
        """Find a manifest in a single search directory."""
        (tmp_path / "myvm.toml").write_text("[vm]\nname='x'\nimage='y'\n")
        result = find_manifest("myvm", [tmp_path])
        assert result == tmp_path / "myvm.toml"

    def test_not_found_raises(self, tmp_path):
        """FileNotFoundError when manifest doesn't exist."""
        with pytest.raises(FileNotFoundError):
            find_manifest("nonexistent", [tmp_path])

    def test_searches_multiple_directories(self, tmp_path):
        """Should search across multiple directories, returning first match."""
        d1 = tmp_path / "dir1"
        d2 = tmp_path / "dir2"
        d1.mkdir()
        d2.mkdir()
        (d2 / "found.toml").write_text("[vm]\nname='x'\nimage='y'\n")
        result = find_manifest("found", [d1, d2])
        assert result == d2 / "found.toml"

    def test_first_directory_wins(self, tmp_path):
        """If manifest exists in multiple dirs, first one wins."""
        d1 = tmp_path / "dir1"
        d2 = tmp_path / "dir2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "dup.toml").write_text("first")
        (d2 / "dup.toml").write_text("second")
        result = find_manifest("dup", [d1, d2])
        assert result == d1 / "dup.toml"

    def test_empty_search_dirs(self):
        """Empty search dirs list should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            find_manifest("anything", [])
