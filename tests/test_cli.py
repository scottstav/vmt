"""Tests for vmt.cli — argument parsing for all subcommands."""

from __future__ import annotations

import pytest

from vmt.cli import build_parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def parser():
    return build_parser()


# ---------------------------------------------------------------------------
# up
# ---------------------------------------------------------------------------

class TestUpCommand:
    """Tests for 'vmt up <name>'."""

    def test_parses_name(self, parser):
        args = parser.parse_args(["up", "arch-sway"])
        assert args.command == "up"
        assert args.name == "arch-sway"


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------

class TestDestroyCommand:
    """Tests for 'vmt destroy <name>'."""

    def test_parses_name(self, parser):
        args = parser.parse_args(["destroy", "arch-sway"])
        assert args.command == "destroy"
        assert args.name == "arch-sway"


# ---------------------------------------------------------------------------
# ssh
# ---------------------------------------------------------------------------

class TestSshCommand:
    """Tests for 'vmt ssh <name> [-- command...]'."""

    def test_parses_name_without_command(self, parser):
        args = parser.parse_args(["ssh", "arch-sway"])
        assert args.command == "ssh"
        assert args.name == "arch-sway"
        assert args.cmd == []

    def test_parses_name_with_command(self, parser):
        args = parser.parse_args(["ssh", "arch-sway", "--", "ls", "-la"])
        assert args.command == "ssh"
        assert args.name == "arch-sway"
        assert args.cmd == ["ls", "-la"]


# ---------------------------------------------------------------------------
# view
# ---------------------------------------------------------------------------

class TestViewCommand:
    """Tests for 'vmt view <name>'."""

    def test_parses_name(self, parser):
        args = parser.parse_args(["view", "arch-sway"])
        assert args.command == "view"
        assert args.name == "arch-sway"


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------

class TestScreenshotCommand:
    """Tests for 'vmt screenshot <name> <remote_path> <local_path>'."""

    def test_parses_all_args(self, parser):
        args = parser.parse_args([
            "screenshot", "arch-sway", "/tmp/shot.png", "./output.png"
        ])
        assert args.command == "screenshot"
        assert args.name == "arch-sway"
        assert args.remote_path == "/tmp/shot.png"
        assert args.local_path == "./output.png"


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------

class TestTestCommand:
    """Tests for 'vmt test <name> --manifest <path>'."""

    def test_parses_with_manifest(self, parser):
        args = parser.parse_args([
            "test", "arch-sway", "--manifest", "tests/sway.toml"
        ])
        assert args.command == "test"
        assert args.name == "arch-sway"
        assert args.manifest == "tests/sway.toml"


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

class TestSnapshotCommand:
    """Tests for 'vmt snapshot <name> <snap_name>'."""

    def test_parses_name_and_snap_name(self, parser):
        args = parser.parse_args(["snapshot", "arch-sway", "clean-boot"])
        assert args.command == "snapshot"
        assert args.name == "arch-sway"
        assert args.snap_name == "clean-boot"


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

class TestRestoreCommand:
    """Tests for 'vmt restore <name> <snap_name>'."""

    def test_parses_name_and_snap_name(self, parser):
        args = parser.parse_args(["restore", "arch-sway", "clean-boot"])
        assert args.command == "restore"
        assert args.name == "arch-sway"
        assert args.snap_name == "clean-boot"


# ---------------------------------------------------------------------------
# update-references
# ---------------------------------------------------------------------------

class TestUpdateReferencesCommand:
    """Tests for 'vmt update-references <name>'."""

    def test_parses_name(self, parser):
        args = parser.parse_args(["update-references", "arch-sway"])
        assert args.command == "update-references"
        assert args.name == "arch-sway"


# ---------------------------------------------------------------------------
# Global flags
# ---------------------------------------------------------------------------

class TestGlobalFlags:
    """Tests for global flags like -v/--verbose."""

    def test_verbose_flag(self, parser):
        args = parser.parse_args(["-v", "up", "arch-sway"])
        assert args.verbose is True

    def test_verbose_long_flag(self, parser):
        args = parser.parse_args(["--verbose", "up", "arch-sway"])
        assert args.verbose is True

    def test_no_verbose_by_default(self, parser):
        args = parser.parse_args(["up", "arch-sway"])
        assert args.verbose is False
