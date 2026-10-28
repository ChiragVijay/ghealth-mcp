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


def _keyring_backend_errors():
    errors: list[Exception] = [OSError(5, "Access denied")]
    if hasattr(token_store, "pywintypes"):
        errors.append(token_store.pywintypes.error(1783, "CredWrite", "The stub received bad data"))
    return errors


@pytest.mark.parametrize("backend_error", _keyring_backend_errors())
def test_refresh_keeps_file_tokens_when_optional_keyring_raises_native_error(monkeypatch, backend_error):
    from ghealth.api.client import _ensure_fresh_tokens

    config = Config(client_id="id", client_secret="secret")
    save_config(config)
    tokens = {"access_token": "expired", "refresh_token": "refresh", "expires_at": 0}
    token_store.save_tokens(tokens)
    refreshed = {"access_token": "fresh", "refresh_token": "refresh", "expires_at": 9999999999}
    monkeypatch.setattr("ghealth.api.client.refresh_access_token", lambda *args: refreshed.copy())

    def fail(*args):
        raise backend_error

    monkeypatch.setattr(token_store.keyring, "set_password", fail)
    _ensure_fresh_tokens(config, tokens)
    assert tokens == refreshed
    assert token_store.load_tokens() == refreshed


@pytest.mark.parametrize("backend_error", _keyring_backend_errors())
def test_explicit_keyring_storage_reports_native_backend_failure(monkeypatch, backend_error):
    save_config(Config(client_id="id", client_secret="secret", token_storage="keyring"))

    def fail(*args):
        raise backend_error

    monkeypatch.setattr(token_store.keyring, "set_password", fail)
    with pytest.raises(RuntimeError, match="Failed to store tokens in OS keyring"):
        token_store.save_tokens({"access_token": "fresh"})


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


@pytest.mark.parametrize("backend_error", [token_store.NoKeyringError("unavailable"), OSError(5, "denied")])
def test_logout_prevents_stale_keyring_account_returning(mock_keyring, monkeypatch, backend_error):
    save_config(Config(client_id="id", client_secret="secret"))
    token_store.save_tokens({"access_token": "account-a"})
    token_store._save_to_file({"access_token": "account-b"})
    original_get_password = token_store.keyring.get_password

    def unavailable(*args):
        raise backend_error

    monkeypatch.setattr(token_store.keyring, "get_password", unavailable)
    if isinstance(backend_error, token_store.NoKeyringError):
        token_store.delete_tokens()
    else:
        with pytest.raises(RuntimeError, match="OS keyring"):
            token_store.delete_tokens()
    monkeypatch.setattr(token_store.keyring, "get_password", original_get_password)
    assert token_store.load_tokens() is None
    assert json.loads(token_store.get_token_path().read_text()) == {}
    token_store.save_tokens({"access_token": "account-c"})
    assert token_store.load_tokens() == {"access_token": "account-c"}


def test_invalid_utf8_credentials_fail_without_keyring_fallback(mock_keyring):
    from ghealth.config import describe_config_problem

    save_config(Config(client_id="id", client_secret="secret"))
    token_store.save_tokens({"access_token": "old-account"})
    token_store.get_token_path().write_bytes(b"\xff")
    assert token_store.load_tokens() is None
    get_config_path().write_bytes(b"\xff")
    assert load_config() is None
    assert "expected UTF-8 JSON" in describe_config_problem()


def test_configuration_diagnostics_never_expose_credential_values():
    from ghealth.config import describe_config_problem

    get_config_path().write_text(
        json.dumps({"client_id": "test-id", "client_secret": "private-secret", "token_storage": "invalid"})
    )
    problem = describe_config_problem()
    assert "token_storage" in problem
    assert "private-secret" not in problem
    assert "test-id" not in problem


def test_configuration_diagnostics_identify_missing_file():
    from ghealth.config import describe_config_problem

    assert "FileNotFoundError" in describe_config_problem()


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
