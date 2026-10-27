import json
import os
import stat

import httpx
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from ghealth.auth import token_store
from ghealth.auth.oauth import revoke_token
from ghealth.config import Config, get_config_path, load_config, parse_credentials_json, save_config
from ghealth.integrations import register_client
from ghealth.local_files import write_private_file
from ghealth.mcp_cli import app


def test_atomic_private_write_preserves_original_on_failure(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text("original")

    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr("ghealth.local_files.os.fsync", fail)
    with pytest.raises(OSError):
        write_private_file(path, "secret")
    assert path.read_text() == "original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes; Windows uses directory ACLs")
def test_private_files_and_agent_config_backup_are_owner_only(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".cursor" / "mcp.json"
    write_private_file(path, '{"mcpServers": {"other": {"env": {"KEY": "test-secret"}}}}')
    register_client("cursor")
    for item in [path, path.with_suffix(".json.ghealth-backup")]:
        assert stat.S_IMODE(item.stat().st_mode) == 0o600


def test_auto_store_does_not_return_stale_account(mock_keyring, monkeypatch) -> None:
    save_config(Config(client_id="id", client_secret="secret"))
    token_store.save_tokens({"access_token": "account-a"})

    def fail(*args):
        raise token_store.KeyringError("locked")

    monkeypatch.setattr(token_store.keyring, "set_password", fail)
    token_store.save_tokens({"access_token": "account-b"})
    assert token_store.load_tokens() == {"access_token": "account-b"}
    token_store.get_token_path().write_text("invalid JSON")
    assert token_store.load_tokens() is None


@pytest.mark.parametrize("document", ["[]", "null", '"text"'])
def test_invalid_config_root_is_recoverable(document) -> None:
    get_config_path().write_text(document)
    assert load_config() is None


@pytest.mark.parametrize("endpoint", ["http://oauth2.googleapis.com/token", "https://example.com/token"])
def test_untrusted_oauth_endpoint_is_rejected(tmp_path, endpoint) -> None:
    with pytest.raises(ValidationError):
        Config(client_id="id", client_secret="secret", token_uri=endpoint)
    path = tmp_path / "download.json"
    path.write_text(
        json.dumps({"installed": {"client_id": "id", "client_secret": "secret", "token_uri": endpoint}})
    )
    with pytest.raises(ValidationError):
        parse_credentials_json(path)


def test_failed_google_revocation_keeps_tokens_for_retry(monkeypatch) -> None:
    save_config(Config(client_id="id", client_secret="secret"))
    token_store.save_tokens({"access_token": "test-access", "refresh_token": "test-refresh"})

    def fail(*args):
        response = httpx.Response(503, request=httpx.Request("POST", "https://oauth2.googleapis.com/revoke"))
        response.raise_for_status()

    monkeypatch.setattr("ghealth.mcp_cli.revoke_token", fail)
    result = CliRunner().invoke(app, ["logout"])
    assert result.exit_code == 1
    tokens = token_store.load_tokens()
    assert tokens is not None and tokens["refresh_token"] == "test-refresh"


def test_already_invalid_token_can_be_cleared(monkeypatch) -> None:
    response = httpx.Response(
        400,
        json={"error": "invalid_token"},
        request=httpx.Request("POST", "https://oauth2.googleapis.com/revoke"),
    )
    monkeypatch.setattr("ghealth.auth.oauth.httpx.post", lambda *args, **kwargs: response)
    revoke_token(Config(client_id="id", client_secret="secret"), "test-refresh")


def test_file_storage_logout_without_optional_keyring(monkeypatch) -> None:
    def unavailable(*args):
        raise token_store.NoKeyringError("No backend")

    save_config(Config(client_id="id", client_secret="secret", token_storage="plaintext"))
    token_store.save_tokens({"access_token": "test-access"})
    monkeypatch.setattr(token_store.keyring, "get_password", unavailable)
    token_store.delete_tokens()
    assert not token_store.get_token_path().exists()


def test_revocation_checks_google_status(monkeypatch) -> None:
    response = httpx.Response(503, request=httpx.Request("POST", "https://oauth2.googleapis.com/revoke"))
    monkeypatch.setattr("ghealth.auth.oauth.httpx.post", lambda *args, **kwargs: response)
    with pytest.raises(httpx.HTTPStatusError):
        revoke_token(Config(client_id="id", client_secret="secret"), "test-refresh")


def test_token_deletion_reports_locked_store(mock_keyring, monkeypatch) -> None:
    token_store.save_tokens({"access_token": "test-access"})

    def fail(*args):
        raise token_store.KeyringError("locked")

    monkeypatch.setattr(token_store.keyring, "delete_password", fail)
    with pytest.raises(RuntimeError, match="OS keyring"):
        token_store.delete_tokens()


def test_codex_custom_registration_is_preserved(monkeypatch) -> None:
    import subprocess

    seen = []
    monkeypatch.setattr("ghealth.integrations.shutil.which", lambda name: "/agent/codex")

    def run(arguments, **kwargs):
        seen.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout='{"transport": {"command": "custom"}}')

    monkeypatch.setattr("ghealth.integrations.subprocess.run", run)
    with pytest.raises(ValueError, match="Existing settings were kept"):
        register_client("codex")
    assert len(seen) == 1 and "get" in seen[0]
