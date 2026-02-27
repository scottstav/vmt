"""SSH client utilities for communicating with VMs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import paramiko


# ── Key discovery ─────────────────────────────────────────────────────

_KEY_NAMES = ("id_ed25519", "id_rsa", "id_ecdsa")


def get_ssh_key_path() -> Path:
    """Find the first available SSH private key in ~/.ssh/.

    Checks for id_ed25519, id_rsa, id_ecdsa in that order.

    Returns:
        Path to the private key file.

    Raises:
        FileNotFoundError: If no supported key is found.
    """
    ssh_dir = Path.home() / ".ssh"
    for name in _KEY_NAMES:
        key = ssh_dir / name
        if key.exists():
            return key
    raise FileNotFoundError(
        f"No SSH private key found in {ssh_dir} "
        f"(checked {', '.join(_KEY_NAMES)})"
    )


def get_ssh_pubkey() -> str:
    """Read the public key corresponding to the private key on disk.

    Returns:
        The public key string (trimmed).

    Raises:
        FileNotFoundError: If the .pub file doesn't exist.
    """
    key_path = get_ssh_key_path()
    pub_path = key_path.with_suffix(key_path.suffix + ".pub")
    if not pub_path.exists():
        raise FileNotFoundError(f"Public key not found: {pub_path}")
    return pub_path.read_text().strip()


# ── RunResult ─────────────────────────────────────────────────────────


@dataclass
class RunResult:
    """Result of a remote command execution."""

    stdout: str
    stderr: str
    returncode: int


# ── SSHClient ─────────────────────────────────────────────────────────


class SSHClient:
    """Thin wrapper around paramiko for VM communication."""

    def __init__(
        self,
        host: str,
        user: str,
        port: int = 22,
        key_path: Path | None = None,
    ) -> None:
        self.host = host
        self.user = user
        self.port = port
        self.key_path = key_path if key_path is not None else get_ssh_key_path()
        self._client: paramiko.SSHClient | None = None

    # ── connection lifecycle ──────────────────────────────────────────

    def connect(self) -> None:
        """Open an SSH connection to the host."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            key_filename=str(self.key_path),
        )
        self._client = client

    def close(self) -> None:
        """Close the SSH connection if open."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _ensure_connected(self) -> paramiko.SSHClient:
        """Return the underlying client, connecting first if needed."""
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    # ── commands ──────────────────────────────────────────────────────

    def run(self, command: str) -> RunResult:
        """Execute a command on the remote host.

        Auto-connects if not already connected.

        Returns:
            RunResult with stdout, stderr, and return code.
        """
        client = self._ensure_connected()
        _stdin, stdout, stderr = client.exec_command(command)
        rc = stdout.channel.recv_exit_status()
        return RunResult(
            stdout=stdout.read().decode(),
            stderr=stderr.read().decode(),
            returncode=rc,
        )

    # ── file transfer ─────────────────────────────────────────────────

    def download(self, remote_path: str, local_path: Path) -> None:
        """Download a file from the remote host via SFTP.

        Creates parent directories for local_path if they don't exist.
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)
        client = self._ensure_connected()
        sftp = client.open_sftp()
        try:
            sftp.get(remote_path, str(local_path))
        finally:
            sftp.close()

    def upload(self, local_path: Path, remote_path: str) -> None:
        """Upload a local file to the remote host via SFTP."""
        client = self._ensure_connected()
        sftp = client.open_sftp()
        try:
            sftp.put(str(local_path), remote_path)
        finally:
            sftp.close()

    # ── readiness polling ─────────────────────────────────────────────

    def wait_until_ready(self, timeout: int = 300, interval: int = 2) -> None:
        """Poll connect() until the VM accepts SSH or timeout is reached.

        Args:
            timeout: Maximum seconds to wait.
            interval: Seconds between attempts.

        Raises:
            TimeoutError: If the host is not reachable within timeout.
        """
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None

        while time.monotonic() < deadline:
            try:
                self.connect()
                return
            except Exception as exc:
                last_err = exc
                time.sleep(interval)

        raise TimeoutError(
            f"SSH to {self.host}:{self.port} not ready after {timeout}s: {last_err}"
        )
