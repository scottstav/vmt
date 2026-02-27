"""Manifest parsing for VM definitions and test scenarios."""

from __future__ import annotations

import tomllib
from pathlib import Path


_VM_REQUIRED_SECTIONS = ("vm", "provision", "ssh")
_VM_REQUIRED_FIELDS = ("name", "image")
_VM_DEFAULTS = {"memory": 2048, "cpus": 2, "disk": 10}

_TEST_REQUIRED_SECTIONS = ("test", "scenario")


def load_vm_manifest(path: Path) -> dict:
    """Load and validate a VM manifest TOML file.

    Required sections: [vm], [provision], [ssh].
    Required vm fields: name, image.
    Defaults applied: memory=2048, cpus=2, disk=10.
    Ensures provision.env exists (defaults to empty dict).

    Raises:
        ValueError: If required sections or fields are missing.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Validate required sections
    for section in _VM_REQUIRED_SECTIONS:
        if section not in data:
            raise ValueError(f"Missing required section: [{section}]")

    # Validate required vm fields
    for field in _VM_REQUIRED_FIELDS:
        if field not in data["vm"]:
            raise ValueError(f"Missing required vm field: {field}")

    # Apply defaults for vm
    for key, default in _VM_DEFAULTS.items():
        data["vm"].setdefault(key, default)

    # Ensure provision.env exists
    data["provision"].setdefault("env", {})

    return data


def load_test_manifest(path: Path) -> dict:
    """Load a test manifest TOML file.

    Required sections: [test], [[scenario]].
    Supports [install], [install.<distro>], and scenario fields:
    name, commands, screenshot, reference, threshold, expect_output.

    Raises:
        ValueError: If required sections are missing.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    for section in _TEST_REQUIRED_SECTIONS:
        if section not in data:
            raise ValueError(f"Missing required section: [{section}]")

    return data


def find_manifest(name: str, search_dirs: list[Path]) -> Path:
    """Find <name>.toml across search directories.

    Returns the path to the first match found.

    Raises:
        FileNotFoundError: If the manifest is not found in any directory.
    """
    filename = f"{name}.toml"
    for d in search_dirs:
        candidate = d / filename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Manifest '{filename}' not found in: {', '.join(str(d) for d in search_dirs) or '(no directories)'}"
    )
