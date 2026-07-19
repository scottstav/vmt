"""Tests for vmt.connect — SSH client utilities."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from vmt.connect import RunResult, SSHClient, get_ssh_key_path, get_ssh_pubkey


# ── get_ssh_key_path ──────────────────────────────────────────────────


class TestGetSSHKeyPath:
    """Tests for get_ssh_key_path()."""

    def test_finds_ed25519_first(self, tmp_path: Path):
        """ed25519 is preferred over rsa and ecdsa."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ed25519").touch()
        (ssh_dir / "id_rsa").touch()

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            result = get_ssh_key_path()

        assert result == ssh_dir / "id_ed25519"

    def test_falls_back_to_rsa(self, tmp_path: Path):
        """Falls back to rsa when ed25519 is absent."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_rsa").touch()

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            result = get_ssh_key_path()

        assert result == ssh_dir / "id_rsa"

    def test_falls_back_to_ecdsa(self, tmp_path: Path):
        """Falls back to ecdsa when ed25519 and rsa are absent."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ecdsa").touch()

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            result = get_ssh_key_path()

        assert result == ssh_dir / "id_ecdsa"

    def test_raises_when_no_key(self, tmp_path: Path):
        """Raises FileNotFoundError when no key exists."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            with pytest.raises(FileNotFoundError):
                get_ssh_key_path()

    def test_vmt_data_dir_key_wins_over_ssh_dir(self, tmp_path: Path):
        """~/.local/share/vmt/id_ed25519 is preferred over ~/.ssh keys."""
        data_dir = tmp_path / ".local" / "share" / "vmt"
        data_dir.mkdir(parents=True)
        (data_dir / "id_ed25519").touch()
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ed25519").touch()

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            result = get_ssh_key_path()

        assert result == data_dir / "id_ed25519"

    def test_vmt_suffixed_key_wins_over_generic(self, tmp_path: Path):
        """~/.ssh/id_ed25519_vmt is preferred over ~/.ssh/id_ed25519."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ed25519_vmt").touch()
        (ssh_dir / "id_ed25519").touch()

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            result = get_ssh_key_path()

        assert result == ssh_dir / "id_ed25519_vmt"

    def test_env_override_wins(self, tmp_path: Path, monkeypatch):
        """$VMT_SSH_KEY beats every discovered location."""
        custom = tmp_path / "custom_key"
        custom.touch()
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ed25519").touch()
        monkeypatch.setenv("VMT_SSH_KEY", str(custom))

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            result = get_ssh_key_path()

        assert result == custom

    def test_env_override_missing_file_raises(self, tmp_path: Path, monkeypatch):
        """$VMT_SSH_KEY pointing at a missing file fails loudly, no fallback."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ed25519").touch()
        monkeypatch.setenv("VMT_SSH_KEY", str(tmp_path / "nope"))

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            with pytest.raises(FileNotFoundError):
                get_ssh_key_path()


# ── get_ssh_pubkey ────────────────────────────────────────────────────


class TestGetSSHPubkey:
    """Tests for get_ssh_pubkey()."""

    def test_reads_pub_file(self, tmp_path: Path):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ed25519").touch()
        (ssh_dir / "id_ed25519.pub").write_text(
            "ssh-ed25519 AAAA... user@host\n"
        )

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            result = get_ssh_pubkey()

        assert result == "ssh-ed25519 AAAA... user@host"

    def test_raises_when_pub_missing(self, tmp_path: Path):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_ed25519").touch()
        # no .pub file

        with patch("vmt.connect.Path.home", return_value=tmp_path):
            with pytest.raises(FileNotFoundError):
                get_ssh_pubkey()


# ── SSHClient ─────────────────────────────────────────────────────────


class TestSSHClientConstructor:
    """Tests for SSHClient.__init__."""

    def test_stores_params(self):
        key = Path("/tmp/fake_key")
        client = SSHClient(host="10.0.0.1", user="vm", port=2222, key_path=key)

        assert client.host == "10.0.0.1"
        assert client.user == "vm"
        assert client.port == 2222
        assert client.key_path == key

    def test_defaults(self):
        with patch("vmt.connect.get_ssh_key_path", return_value=Path("/k")):
            client = SSHClient(host="h", user="u")

        assert client.port == 22
        assert client.key_path == Path("/k")


class TestSSHClientRun:
    """Tests for SSHClient.run() — uses mocked paramiko."""

    @staticmethod
    def _make_client() -> SSHClient:
        return SSHClient(
            host="10.0.0.1",
            user="vm",
            key_path=Path("/tmp/fake_key"),
        )

    @staticmethod
    def _mock_exec(stdout_data: str, stderr_data: str, rc: int):
        """Build the three-tuple that paramiko exec_command returns."""
        mock_stdin = MagicMock()

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = stdout_data.encode()
        mock_stdout.channel.recv_exit_status.return_value = rc

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = stderr_data.encode()

        return mock_stdin, mock_stdout, mock_stderr

    @patch("vmt.connect.paramiko.SSHClient")
    def test_run_returns_run_result(self, MockSSHClient):
        mock_ssh = MockSSHClient.return_value
        mock_ssh.exec_command.return_value = self._mock_exec("hello\n", "", 0)

        client = self._make_client()
        result = client.run("echo hello")

        assert isinstance(result, RunResult)
        assert result.stdout == "hello\n"
        assert result.stderr == ""
        assert result.returncode == 0

    @patch("vmt.connect.paramiko.SSHClient")
    def test_run_captures_stderr(self, MockSSHClient):
        mock_ssh = MockSSHClient.return_value
        mock_ssh.exec_command.return_value = self._mock_exec("", "err\n", 1)

        client = self._make_client()
        result = client.run("bad-cmd")

        assert result.stderr == "err\n"
        assert result.returncode == 1


class TestSSHClientDownload:
    """Tests for SSHClient.download()."""

    @patch("vmt.connect.paramiko.SSHClient")
    def test_download_calls_sftp_get(self, MockSSHClient, tmp_path: Path):
        mock_ssh = MockSSHClient.return_value
        mock_sftp = MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp

        client = SSHClient(
            host="h", user="u", key_path=Path("/tmp/fake_key")
        )
        local = tmp_path / "sub" / "file.png"
        client.download("/remote/file.png", local)

        mock_sftp.get.assert_called_once_with("/remote/file.png", str(local))
        # parent directory should have been created
        assert local.parent.is_dir()


class TestSSHClientUpload:
    """Tests for SSHClient.upload()."""

    @patch("vmt.connect.paramiko.SSHClient")
    def test_upload_calls_sftp_put(self, MockSSHClient, tmp_path: Path):
        mock_ssh = MockSSHClient.return_value
        mock_sftp = MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp

        client = SSHClient(
            host="h", user="u", key_path=Path("/tmp/fake_key")
        )
        local = tmp_path / "file.txt"
        local.write_text("data")
        client.upload(local, "/remote/file.txt")

        mock_sftp.put.assert_called_once_with(str(local), "/remote/file.txt")


class TestSSHClientWaitUntilReady:
    """Tests for SSHClient.wait_until_ready()."""

    def test_method_exists(self):
        client = SSHClient(
            host="h", user="u", key_path=Path("/tmp/fake_key")
        )
        assert callable(getattr(client, "wait_until_ready", None))

    @patch("vmt.connect.time.sleep", return_value=None)
    @patch("vmt.connect.paramiko.SSHClient")
    def test_raises_timeout(self, MockSSHClient, mock_sleep):
        mock_ssh = MockSSHClient.return_value
        mock_ssh.connect.side_effect = OSError("refused")

        client = SSHClient(
            host="h", user="u", key_path=Path("/tmp/fake_key")
        )
        with pytest.raises(TimeoutError):
            client.wait_until_ready(timeout=4, interval=1)

    @patch("vmt.connect.time.sleep", return_value=None)
    @patch("vmt.connect.paramiko.SSHClient")
    def test_succeeds_after_retries(self, MockSSHClient, mock_sleep):
        mock_ssh = MockSSHClient.return_value
        # Fail twice, then succeed
        mock_ssh.connect.side_effect = [OSError("refused"), OSError("refused"), None]

        client = SSHClient(
            host="h", user="u", key_path=Path("/tmp/fake_key")
        )
        # Should not raise
        client.wait_until_ready(timeout=120, interval=1)
