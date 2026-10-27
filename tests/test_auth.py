import json
import time

import pytest
from keyring.errors import KeyringError
from typer.testing import CliRunner

import ghealth.cli
from ghealth.auth.scopes import AUTH_STATUS_IDENTITY_SCOPES, get_scopes_for_login
from ghealth.auth.token_store import delete_tokens, load_tokens, save_tokens
from ghealth.cli import app
from ghealth.config import Config, load_config, parse_credentials_json, save_config


def test_parse_credentials_json(tmp_path) -> None:
    # Test valid installed format
    installed_creds = {
        "installed": {
            "client_id": "test_id",
            "client_secret": "test_secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    }
    file_path = tmp_path / "creds1.json"
    file_path.write_text(json.dumps(installed_creds))
    parsed = parse_credentials_json(file_path)
    assert parsed["client_id"] == "test_id"
    assert parsed["client_secret"] == "test_secret"

    # Test valid web format
    web_creds = {
        "web": {
            "client_id": "test_id_web",
            "client_secret": "test_secret_web",
        },
    }
    file_path2 = tmp_path / "creds2.json"
    file_path2.write_text(json.dumps(web_creds))
    parsed2 = parse_credentials_json(file_path2)
    assert parsed2["client_id"] == "test_id_web"
    assert parsed2["client_secret"] == "test_secret_web"
    assert parsed2["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"

    # Test missing fields
    invalid_creds = {"installed": {"client_id": "test_id"}}
    file_path3 = tmp_path / "creds3.json"
    file_path3.write_text(json.dumps(invalid_creds))
    with pytest.raises(ValueError, match="Missing required key 'client_secret'"):
        parse_credentials_json(file_path3)


def test_config_management() -> None:
    assert load_config() is None

    conf = Config(client_id="123", client_secret="abc", token_storage="plaintext")
    save_config(conf)

    loaded = load_config()
    assert loaded is not None
    assert loaded.client_id == "123"
    assert loaded.client_secret == "abc"
    assert loaded.token_storage == "plaintext"


def test_token_store_plaintext() -> None:
    conf = Config(client_id="123", client_secret="abc", token_storage="plaintext")
    save_config(conf)

    assert load_tokens() is None

    tokens = {"access_token": "foo", "refresh_token": "bar", "expires_at": 9999}
    save_tokens(tokens)

    loaded = load_tokens()
    assert loaded == tokens

    delete_tokens()
    assert load_tokens() is None


def test_token_store_keyring(mock_keyring) -> None:
    conf = Config(client_id="123", client_secret="abc", token_storage="keyring")
    save_config(conf)

    assert load_tokens() is None

    tokens = {"access_token": "foo_key", "refresh_token": "bar_key", "expires_at": 9999}
    save_tokens(tokens)

    loaded = load_tokens()
    assert loaded == tokens

    # Ensure it's in the mocked keyring store
    assert ("ghealth", "tokens") in mock_keyring

    delete_tokens()
    assert load_tokens() is None
    assert ("ghealth", "tokens") not in mock_keyring


def test_token_store_auto_mode(mock_keyring) -> None:
    """Auto mode dual-writes and reads the current local file first."""
    conf = Config(client_id="123", client_secret="abc", token_storage="auto")
    save_config(conf)

    assert load_tokens() is None

    tokens = {"access_token": "auto_a", "refresh_token": "auto_r", "expires_at": 9999}
    save_tokens(tokens)

    # Verify dual-write: both keyring and file should contain the tokens
    assert ("ghealth", "tokens") in mock_keyring
    from ghealth.auth.token_store import get_token_path

    token_file = get_token_path()
    assert token_file.exists()
    file_tokens = json.loads(token_file.read_text(encoding="utf-8"))
    assert file_tokens["access_token"] == "auto_a"

    # Load should return the authoritative local file.
    loaded = load_tokens()
    assert loaded == tokens

    delete_tokens()
    assert load_tokens() is None


def test_token_store_auto_keyring_fails_reads_file(mock_keyring, monkeypatch) -> None:
    """When keyring is unavailable on read, auto mode falls back to the local file."""
    conf = Config(client_id="123", client_secret="abc", token_storage="auto")
    save_config(conf)

    tokens = {"access_token": "fb_a", "refresh_token": "fb_r", "expires_at": 9999}
    save_tokens(tokens)

    # Simulate keyring becoming unavailable (e.g. sandboxed process)
    import ghealth.auth.token_store

    def _raise_keyring_error(service_name: str, username: str) -> str | None:
        raise KeyringError("sandbox blocked")

    monkeypatch.setattr(ghealth.auth.token_store.keyring, "get_password", _raise_keyring_error)

    loaded = load_tokens()
    assert loaded is not None
    assert loaded["access_token"] == "fb_a"


def test_token_store_auto_file_permissions(mock_keyring) -> None:
    """Auto mode sets restrictive file permissions (0600) on the token file."""
    import stat

    conf = Config(client_id="123", client_secret="abc", token_storage="auto")
    save_config(conf)

    tokens = {"access_token": "perm_a", "refresh_token": "perm_r", "expires_at": 9999}
    save_tokens(tokens)

    from ghealth.auth.token_store import get_token_path

    token_file = get_token_path()
    file_mode = token_file.stat().st_mode
    import os

    if os.name == "nt":
        # Windows chmod only controls the read-only bit; POSIX mode bits do not model NTFS ACLs.
        assert file_mode & stat.S_IWUSR
    else:
        assert file_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR  # 0600


def test_scopes_expansion() -> None:
    # Profile
    scopes = get_scopes_for_login(scope_profile="sleep")
    assert "https://www.googleapis.com/auth/googlehealth.sleep.readonly" in scopes
    for identity_scope in AUTH_STATUS_IDENTITY_SCOPES:
        assert identity_scope in scopes

    # Alias
    scopes2 = get_scopes_for_login(scopes_str="sleep.readonly,nutrition.readonly")
    assert "https://www.googleapis.com/auth/googlehealth.sleep.readonly" in scopes2
    assert "https://www.googleapis.com/auth/googlehealth.nutrition.readonly" in scopes2
    for identity_scope in AUTH_STATUS_IDENTITY_SCOPES:
        assert identity_scope in scopes2

    scopes_cloud = get_scopes_for_login(scopes_str="cloud-platform")
    assert "https://www.googleapis.com/auth/cloud-platform" in scopes_cloud
    assert "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly" not in scopes_cloud

    # Full URLs & Raw parts
    scopes3 = get_scopes_for_login(scopes_str="https://foo.bar,activity_and_fitness.readonly")
    assert "https://foo.bar" in scopes3
    assert "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly" in scopes3
    for identity_scope in AUTH_STATUS_IDENTITY_SCOPES:
        assert identity_scope in scopes3

    # Invalid profile
    with pytest.raises(ValueError, match="Unknown scope profile"):
        get_scopes_for_login(scope_profile="invalid_profile")


def test_custom_scopes_are_merged_with_scope_profile() -> None:
    scopes = get_scopes_for_login(scope_profile="sleep", scopes_str="cloud-platform")

    assert "https://www.googleapis.com/auth/googlehealth.sleep.readonly" in scopes
    assert "https://www.googleapis.com/auth/cloud-platform" in scopes
    for identity_scope in AUTH_STATUS_IDENTITY_SCOPES:
        assert identity_scope in scopes


def test_cli_login_help_mentions_webhook_scope_shortcut() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["auth", "login", "--help"])

    assert res.exit_code == 0
    assert "--with-webhooks" in res.stdout


def test_cli_configure_validation() -> None:
    runner = CliRunner()

    # No args and no config should exit with code 2
    res = runner.invoke(app, ["auth", "configure"])
    assert res.exit_code == 2

    # Plaintext storage request without flag should exit with code 2
    res = runner.invoke(app, ["auth", "configure", "--token-storage", "plaintext"])
    assert res.exit_code == 2
    assert "risk" in res.stdout


def test_cli_configure_success(tmp_path) -> None:
    runner = CliRunner()
    creds = {
        "installed": {
            "client_id": "cli_id",
            "client_secret": "cli_secret",
        },
    }
    creds_file = tmp_path / "client_secret.json"
    creds_file.write_text(json.dumps(creds))

    # Test configuration with plaintext and risk flag
    res = runner.invoke(
        app,
        [
            "auth",
            "configure",
            "--credentials",
            str(creds_file),
            "--token-storage",
            "plaintext",
            "--i-understand-health-data-risk",
        ],
    )
    assert res.exit_code == 0
    assert "Success" in res.stdout
    assert "plaintext" in res.stdout

    # Verify config saved correctly
    conf = load_config()
    assert conf is not None
    assert conf.client_id == "cli_id"
    assert conf.token_storage == "plaintext"


def test_cli_status_no_auth() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["auth", "status"])
    assert res.exit_code == 3
    assert "Error" in res.stdout


def test_cli_status_success(mock_keyring) -> None:
    runner = CliRunner()

    conf = Config(client_id="123", client_secret="abc", token_storage="auto")
    save_config(conf)

    tokens = {
        "access_token": "t",
        "refresh_token": "r",
        "expires_at": int(time.time()) + 3600,
        "scope": "sleep",
    }
    save_tokens(tokens)

    # Table view
    res = runner.invoke(app, ["auth", "status"])
    assert res.exit_code == 0
    assert "Authenticated" in res.stdout
    assert "auto" in res.stdout

    # JSON view
    res_json = runner.invoke(app, ["--format", "json", "auth", "status"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["authenticated"] is True
    assert data["token_storage_backend"] == "auto"


def test_cli_logout(mock_keyring) -> None:
    runner = CliRunner()

    conf = Config(client_id="123", client_secret="abc", token_storage="keyring")
    save_config(conf)

    tokens = {"access_token": "t", "refresh_token": "r", "expires_at": 9999, "scope": "sleep"}
    save_tokens(tokens)

    assert load_tokens() is not None

    res = runner.invoke(app, ["auth", "logout"])
    assert res.exit_code == 0
    assert "Logged out successfully" in res.stdout

    assert load_tokens() is None


def test_cli_scopes(mock_keyring) -> None:
    runner = CliRunner()

    conf = Config(client_id="123", client_secret="abc", token_storage="keyring")
    save_config(conf)

    tokens = {
        "access_token": "t",
        "refresh_token": "r",
        "expires_at": 9999,
        "scope": "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    }
    save_tokens(tokens)

    res = runner.invoke(app, ["--format", "json", "auth", "scopes"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data == ["https://www.googleapis.com/auth/googlehealth.sleep.readonly"]


def test_cli_refresh(mock_keyring, monkeypatch) -> None:
    runner = CliRunner()

    conf = Config(client_id="123", client_secret="abc", token_storage="keyring")
    save_config(conf)

    tokens = {"access_token": "old_t", "refresh_token": "r_token", "expires_at": 100}
    save_tokens(tokens)

    # Mock the actual OAuth refresh request to Google
    def mock_refresh(cfg, ref_t):
        assert cfg.client_id == "123"
        assert ref_t == "r_token"
        return {
            "access_token": "new_t",
            "refresh_token": "r_token",
            "expires_at": 99999,
            "scope": "sleep",
        }

    monkeypatch.setattr(ghealth.cli, "refresh_access_token", mock_refresh)

    res = runner.invoke(app, ["auth", "refresh"])
    assert res.exit_code == 0
    assert "Success" in res.stdout

    new_t = load_tokens()
    assert new_t is not None
    assert new_t["access_token"] == "new_t"


def test_cli_revoke(mock_keyring, monkeypatch) -> None:
    runner = CliRunner()

    conf = Config(client_id="123", client_secret="abc", token_storage="keyring")
    save_config(conf)

    tokens = {"access_token": "t", "refresh_token": "r", "expires_at": 9999}
    save_tokens(tokens)

    revoked = []

    def mock_revoke(cfg, tok) -> None:
        revoked.append(tok)

    monkeypatch.setattr(ghealth.cli, "revoke_token", mock_revoke)

    res = runner.invoke(app, ["auth", "revoke"])
    assert res.exit_code == 0
    assert "revoked successfully" in res.stdout
    assert "r" in revoked

    assert load_tokens() is None
