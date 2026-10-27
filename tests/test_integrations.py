import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ghealth.config import Config
from ghealth.integrations import register_client, server_command
from ghealth.mcp_cli import app


@pytest.mark.parametrize("client", ["codex", "claude"])
def test_register_cli_uses_absolute_server_and_no_shell(monkeypatch, client) -> None:
    seen = []
    monkeypatch.setattr("ghealth.integrations.shutil.which", lambda name: f"/agent/{name}")

    def run(arguments, **kwargs):
        seen.append((arguments, kwargs))
        if "get" in arguments:
            return subprocess.CompletedProcess(arguments, 1)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr("ghealth.integrations.subprocess.run", run)
    assert "Connected" in register_client(client)
    arguments, kwargs = seen[-1]
    assert arguments[-4:] == ["--", *server_command()]
    assert not kwargs.get("shell")
    assert "--scope" in arguments if client == "claude" else "--scope" not in arguments


def test_register_cli_failure_does_not_echo_agent_secrets(monkeypatch) -> None:
    monkeypatch.setattr("ghealth.integrations.shutil.which", lambda name: f"/agent/{name}")
    monkeypatch.setattr(
        "ghealth.integrations.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, stderr="secret-from-agent-config"),
    )
    with pytest.raises(RuntimeError, match="Your Google sign-in is saved") as error:
        register_client("codex")
    assert "secret-from-agent-config" not in str(error.value)


def test_missing_agent_has_recovery_command(monkeypatch) -> None:
    monkeypatch.setattr("ghealth.integrations.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="ghealth-mcp connect --client codex"):
        register_client("codex")


def test_cursor_merges_and_backs_up_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".cursor" / "mcp.json"
    path.parent.mkdir()
    original = {"mcpServers": {"other": {"command": "other-server"}}, "extraSetting": True}
    path.write_text(json.dumps(original))
    assert "Connected" in register_client("cursor")
    result = json.loads(path.read_text())
    assert result["extraSetting"]
    assert result["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert result["mcpServers"]["ghealth"]["command"] == server_command()[0]
    assert json.loads(path.with_suffix(".json.ghealth-backup").read_text()) == original
    assert "Already connected" in register_client("cursor")
    assert json.loads(path.with_suffix(".json.ghealth-backup").read_text()) == original


@pytest.mark.parametrize(
    "document",
    ["invalid JSON", "[]", '{"mcpServers": []}', '{"mcpServers": {"ghealth": {"command": "custom-server"}}}'],
)
def test_cursor_preserves_invalid_or_conflicting_config(tmp_path, monkeypatch, document) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text(document)
    with pytest.raises((ValueError, TypeError)):
        register_client("cursor")
    assert path.read_text() == document


def test_claude_desktop_windows_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ghealth.integrations.sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert "Connected" in register_client("claude-desktop")
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    entry = json.loads(path.read_text())["mcpServers"]["ghealth"]
    assert [entry["command"], *entry["args"]] == server_command()
    assert "type" not in entry


def test_setup_signs_in_verifies_and_connects_in_order(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr("ghealth.mcp_cli.load_config", lambda: Config(client_id="id", client_secret="secret"))
    monkeypatch.setattr("ghealth.mcp_cli.login_desktop", lambda *args, **kwargs: seen.append("login"))
    monkeypatch.setattr("ghealth.mcp_cli._verify_connection", lambda: seen.append("verify"))

    def register(client):
        seen.append(client)
        return "Connected to codex"

    monkeypatch.setattr("ghealth.mcp_cli.register_client", register)
    result = CliRunner().invoke(app, ["setup", "--client", "codex"])
    assert result.exit_code == 0, result.output
    assert seen == ["login", "verify", "codex"]
    assert "connection verified" in result.output


def test_setup_does_not_report_success_when_google_rejects_connection(monkeypatch) -> None:
    monkeypatch.setattr("ghealth.mcp_cli.load_config", lambda: Config(client_id="id", client_secret="secret"))
    monkeypatch.setattr("ghealth.mcp_cli.login_desktop", lambda *args, **kwargs: None)

    def reject():
        raise RuntimeError("Enable Google Health API in your Cloud project.")

    monkeypatch.setattr("ghealth.mcp_cli._verify_connection", reject)
    monkeypatch.setattr(
        "ghealth.mcp_cli.register_client", lambda client: pytest.fail("Must verify Google first")
    )
    result = CliRunner().invoke(app, ["setup", "--client", "codex"])
    assert result.exit_code == 1
    assert "Enable Google Health API" in result.output
    assert "connection verified" not in result.output


def test_connect_does_not_repeat_google_login(monkeypatch) -> None:
    monkeypatch.setattr("ghealth.mcp_cli.register_client", lambda client: "Connected to cursor")
    monkeypatch.setattr(
        "ghealth.mcp_cli.login_desktop", lambda *args, **kwargs: pytest.fail("No login needed")
    )
    result = CliRunner().invoke(app, ["connect", "--client", "cursor"])
    assert result.exit_code == 0
