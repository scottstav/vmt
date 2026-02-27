"""Argparse-based CLI for vmt — visual VM testing."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from vmt.connect import SSHClient
from vmt.manifest import load_test_manifest
from vmt.screenshot import compare_screenshots, generate_diff_image
from vmt.vm import VMManager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Manager helper
# ---------------------------------------------------------------------------


def _get_manager() -> VMManager:
    """Create a VMManager with the built-in manifests directory."""
    manifest_dir = Path(__file__).resolve().parent.parent / "manifests"
    return VMManager(manifest_dirs=[manifest_dir])


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_up(args: argparse.Namespace) -> None:
    """Boot a VM."""
    mgr = _get_manager()
    try:
        info = mgr.up(args.name)
        print(f"VM '{info['name']}' is up")
        print(f"  IP:         {info['ip']}")
        print(f"  SSH:        ssh {info['ssh_user']}@{info['ip']} -p {info['ssh_port']}")
        print(f"  SPICE port: {info['spice_port']}")
    finally:
        mgr.close()


def cmd_destroy(args: argparse.Namespace) -> None:
    """Tear down a VM."""
    mgr = _get_manager()
    try:
        mgr.destroy(args.name)
        print(f"VM '{args.name}' destroyed")
    finally:
        mgr.close()


def cmd_ssh(args: argparse.Namespace) -> None:
    """SSH into a VM or run a command."""
    mgr = _get_manager()
    try:
        info = mgr.get_info(args.name)
        if info is None:
            print(f"VM '{args.name}' is not running", file=sys.stderr)
            sys.exit(1)

        ip = info["ip"]
        ssh_user = info.get("ssh_user", "root")
        ssh_port = info.get("ssh_port", 22)

        if not args.cmd:
            # Interactive SSH — replace process
            os.execvp("ssh", [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-p", str(ssh_port),
                f"{ssh_user}@{ip}",
            ])
        else:
            # Non-interactive — run command via SSHClient
            client = SSHClient(host=ip, user=ssh_user, port=ssh_port)
            try:
                result = client.run(" ".join(args.cmd))
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, end="", file=sys.stderr)
                sys.exit(result.returncode)
            finally:
                client.close()
    finally:
        mgr.close()


def cmd_view(args: argparse.Namespace) -> None:
    """Open SPICE viewer for a VM."""
    mgr = _get_manager()
    try:
        info = mgr.get_info(args.name)
        if info is None:
            print(f"VM '{args.name}' is not running", file=sys.stderr)
            sys.exit(1)

        port = info["spice_port"]
        if port is None:
            print(f"No SPICE port found for VM '{args.name}'", file=sys.stderr)
            sys.exit(1)

        subprocess.Popen(
            ["remote-viewer", f"spice://127.0.0.1:{port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Opened SPICE viewer on port {port}")
    finally:
        mgr.close()


def cmd_screenshot(args: argparse.Namespace) -> None:
    """SCP a file from a VM."""
    mgr = _get_manager()
    try:
        info = mgr.get_info(args.name)
        if info is None:
            print(f"VM '{args.name}' is not running", file=sys.stderr)
            sys.exit(1)

        ip = info["ip"]
        ssh_user = info.get("ssh_user", "root")

        client = SSHClient(host=ip, user=ssh_user)
        try:
            client.download(args.remote_path, Path(args.local_path))
            print(f"Downloaded {args.remote_path} → {args.local_path}")
        finally:
            client.close()
    finally:
        mgr.close()


def cmd_test(args: argparse.Namespace) -> None:
    """Run test scenarios from a test manifest."""
    manifest_path = Path(args.manifest)
    manifest = load_test_manifest(manifest_path)

    mgr = _get_manager()
    try:
        info = mgr.get_info(args.name)
        if info is None:
            print(f"VM '{args.name}' is not running", file=sys.stderr)
            sys.exit(1)

        ip = info["ip"]
        ssh_user = info.get("ssh_user", "root")

        client = SSHClient(host=ip, user=ssh_user)
        failures = []
        try:
            for scenario in manifest["scenario"]:
                name = scenario["name"]
                print(f"--- Scenario: {name} ---")

                # Run commands
                for cmd in scenario.get("commands", []):
                    log.debug("Running: %s", cmd)
                    result = client.run(cmd)
                    if result.stdout:
                        print(result.stdout, end="")

                    # Check expect_output if present
                    expect = scenario.get("expect_output")
                    if expect is not None:
                        if expect not in result.stdout:
                            msg = (
                                f"[{name}] Expected output '{expect}' "
                                f"not found in: {result.stdout.strip()}"
                            )
                            print(f"FAIL: {msg}")
                            failures.append(msg)

                # Take screenshot if specified
                screenshot_remote = scenario.get("screenshot")
                if screenshot_remote:
                    local_screenshot = Path(f".vmt/screenshots/{name}.png")
                    client.download(screenshot_remote, local_screenshot)
                    print(f"  Screenshot saved: {local_screenshot}")

                    # Compare against reference if specified
                    reference = scenario.get("reference")
                    if reference:
                        ref_path = manifest_path.parent / reference
                        threshold = scenario.get("threshold", 0.95)

                        if not ref_path.exists():
                            msg = f"[{name}] Reference not found: {ref_path}"
                            print(f"FAIL: {msg}")
                            failures.append(msg)
                            continue

                        passed, score = compare_screenshots(
                            local_screenshot, ref_path, threshold=threshold
                        )
                        if passed:
                            print(f"  SSIM: {score:.4f} >= {threshold} — PASS")
                        else:
                            diff_path = Path(f".vmt/diffs/{name}-diff.png")
                            generate_diff_image(local_screenshot, ref_path, diff_path)
                            msg = (
                                f"[{name}] SSIM {score:.4f} < {threshold} "
                                f"(diff: {diff_path})"
                            )
                            print(f"FAIL: {msg}")
                            failures.append(msg)
        finally:
            client.close()

        if failures:
            print(f"\n{len(failures)} scenario(s) failed:")
            for f in failures:
                print(f"  - {f}")
            sys.exit(1)
        else:
            print(f"\nAll {len(manifest['scenario'])} scenario(s) passed")
    finally:
        mgr.close()


def cmd_snapshot(args: argparse.Namespace) -> None:
    """Create a snapshot of a VM."""
    mgr = _get_manager()
    try:
        mgr.snapshot(args.name, args.snap_name)
        print(f"Snapshot '{args.snap_name}' created for VM '{args.name}'")
    finally:
        mgr.close()


def cmd_restore(args: argparse.Namespace) -> None:
    """Restore a VM to a snapshot."""
    mgr = _get_manager()
    try:
        mgr.restore(args.name, args.snap_name)
        print(f"VM '{args.name}' restored to snapshot '{args.snap_name}'")
    finally:
        mgr.close()


def cmd_update_references(args: argparse.Namespace) -> None:
    """Placeholder for updating reference screenshots."""
    print("not yet implemented")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for vmt."""
    parser = argparse.ArgumentParser(
        prog="vmt",
        description="Visual VM testing for Wayland applications",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )

    sub = parser.add_subparsers(dest="command")

    # up
    p_up = sub.add_parser("up", help="Boot a VM")
    p_up.add_argument("name", help="VM name")

    # destroy
    p_destroy = sub.add_parser("destroy", help="Tear down a VM")
    p_destroy.add_argument("name", help="VM name")

    # ssh
    p_ssh = sub.add_parser("ssh", help="SSH into a VM or run a command")
    p_ssh.add_argument("name", help="VM name")
    p_ssh.add_argument("cmd", nargs="*", default=[], help="Command to run")

    # view
    p_view = sub.add_parser("view", help="Open SPICE viewer")
    p_view.add_argument("name", help="VM name")

    # screenshot
    p_screenshot = sub.add_parser("screenshot", help="SCP a file from a VM")
    p_screenshot.add_argument("name", help="VM name")
    p_screenshot.add_argument("remote_path", help="Remote file path")
    p_screenshot.add_argument("local_path", help="Local file path")

    # test
    p_test = sub.add_parser("test", help="Run test scenarios")
    p_test.add_argument("name", help="VM name")
    p_test.add_argument("--manifest", required=True, help="Path to test manifest")

    # snapshot
    p_snapshot = sub.add_parser("snapshot", help="Create a VM snapshot")
    p_snapshot.add_argument("name", help="VM name")
    p_snapshot.add_argument("snap_name", help="Snapshot name")

    # restore
    p_restore = sub.add_parser("restore", help="Restore a VM snapshot")
    p_restore.add_argument("name", help="VM name")
    p_restore.add_argument("snap_name", help="Snapshot name")

    # update-references
    p_update = sub.add_parser("update-references", help="Update reference screenshots")
    p_update.add_argument("name", help="VM name")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the appropriate command handler."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    dispatch = {
        "up": cmd_up,
        "destroy": cmd_destroy,
        "ssh": cmd_ssh,
        "view": cmd_view,
        "screenshot": cmd_screenshot,
        "test": cmd_test,
        "snapshot": cmd_snapshot,
        "restore": cmd_restore,
        "update-references": cmd_update_references,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
