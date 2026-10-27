"""Protocol and schema regressions, using documented Google v4 field names."""

import json
import sys
import time

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver.exceptions import ToolError
from typer.testing import CliRunner

from ghealth.api.client import GHealthApiClient
from ghealth.config import Config
from ghealth.mcp_cli import app
from ghealth.server import create_server


def call(server, name, arguments):
    return anyio.run(server.call_tool, name, arguments)


@pytest.mark.parametrize(
    ("tool", "arguments", "method", "path", "response"),
    [
        (
            "get_user",
            {"resource": "identity"},
            "GET",
            "/v4/users/me/identity",
            {"name": "users/me/identity", "healthUserId": "example-user"},
        ),
        (
            "get_user",
            {"resource": "profile"},
            "GET",
            "/v4/users/me/profile",
            {"name": "users/me/profile", "age": 30},
        ),
        (
            "get_user",
            {"resource": "settings"},
            "GET",
            "/v4/users/me/settings",
            {"name": "users/me/settings", "timeZone": "America/Chicago"},
        ),
        (
            "list_paired_devices",
            {},
            "GET",
            "/v4/users/me/pairedDevices",
            {
                "pairedDevices": [{"name": "users/me/pairedDevices/123", "deviceType": "TRACKER"}],
                "nextPageToken": "devices-2",
            },
        ),
        (
            "get_paired_device",
            {"device_id": "123"},
            "GET",
            "/v4/users/me/pairedDevices/123",
            {
                "name": "users/me/pairedDevices/123",
            },
        ),
        (
            "list_data_points",
            {"data_type": "steps", "page_token": "page-2"},
            "GET",
            "/v4/users/me/dataTypes/steps/dataPoints",
            {
                "dataPoints": [{"name": "users/me/dataTypes/steps/dataPoints/abc", "steps": {"count": "42"}}],
                "nextPageToken": "page-3",
            },
        ),
        (
            "get_data_point",
            {"data_type": "steps", "data_point_id": "abc"},
            "GET",
            "/v4/users/me/dataTypes/steps/dataPoints/abc",
            {"steps": {"count": "42"}},
        ),
        (
            "reconcile_data_points",
            {"data_type": "steps"},
            "GET",
            "/v4/users/me/dataTypes/steps/dataPoints:reconcile",
            {"dataPoints": [{"steps": {"count": "42"}}]},
        ),
        (
            "daily_rollup_data_points",
            {
                "data_type": "steps",
                "start_date": "2026-10-01",
                "end_date": "2026-10-02",
            },
            "POST",
            "/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp",
            {
                "rollupDataPoints": [
                    {
                        "civilStartTime": {"date": {"year": 2026, "month": 10, "day": 1}},
                        "steps": {"countSum": "42"},
                    }
                ],
            },
        ),
        (
            "rollup_data_points",
            {
                "data_type": "steps",
                "start_time": "2026-10-01T00:00:00Z",
                "end_time": "2026-10-02T00:00:00Z",
                "window_size": "3600s",
            },
            "POST",
            "/v4/users/me/dataTypes/steps/dataPoints:rollUp",
            {
                "rollupDataPoints": [{"startTime": "2026-10-01T00:00:00Z", "steps": {"countSum": "42"}}],
                "nextPageToken": "rollup-2",
            },
        ),
    ],
)
def test_google_json_passthrough(tool, arguments, method, path, response) -> None:
    seen = []

    def handle(request):
        assert request.method == method
        assert request.url.path == path
        assert request.headers["Authorization"] == "Bearer test-access"
        seen.append(request)
        return httpx.Response(200, json=response)

    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="https://health.googleapis.com"
    ) as http:
        server = create_server(
            client_factory=lambda: GHealthApiClient(
                Config(client_id="test", client_secret="test"),
                {"access_token": "test-access"},
                client=http,
            )
        )
        result = call(server, tool, arguments)
    assert not result.is_error
    assert result.structured_content == response
    assert json.loads(result.content[0].text) == response
    if "page_token" in arguments:
        assert seen[0].url.params["pageToken"] == arguments["page_token"]
    if tool == "daily_rollup_data_points":
        assert json.loads(seen[0].content)["range"]["start"]["date"]["day"] == 1


def test_readonly_discovery_and_opt_in_writes() -> None:
    tools = anyio.run(create_server().list_tools)
    assert len(tools) == 10
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)
    assert "create_data_point" not in {tool.name for tool in tools}
    writable = {tool.name: tool for tool in anyio.run(create_server(allow_writes=True).list_tools)}
    assert len(writable) == 13
    annotations = writable["delete_data_points"].annotations
    assert annotations is not None and annotations.destructive_hint
    catalog = call(create_server(), "list_data_types", {}).structured_content
    assert any(row["data_type"] == "steps" for row in catalog["dataTypes"])


@pytest.mark.parametrize(
    "arguments",
    [
        {"data_type": "../profile"},
        {"data_type": "steps", "page_size": 0},
        {"data_type": "steps", "page_size": 10001},
    ],
)
def test_invalid_arguments_never_reach_google(arguments) -> None:
    def fail():
        pytest.fail("Invalid input must not create a client")

    with pytest.raises(ToolError):
        call(create_server(client_factory=fail), "list_data_points", arguments)


def test_missing_auth_is_actionable(monkeypatch) -> None:
    monkeypatch.setattr("ghealth.api.client.load_config", lambda: None)
    with pytest.raises(ToolError, match="ghealth-mcp setup"):
        call(create_server(), "get_user", {})


def test_refresh_then_query(monkeypatch) -> None:
    from ghealth.api.client import create_authenticated_client

    config = Config(client_id="test", client_secret="test")
    tokens = {"access_token": "expired", "refresh_token": "refresh-test", "expires_at": 0}
    saved = []
    monkeypatch.setattr("ghealth.api.client.load_config", lambda: config)
    monkeypatch.setattr("ghealth.api.client.load_tokens", lambda: tokens.copy())
    monkeypatch.setattr(
        "ghealth.api.client.refresh_access_token",
        lambda *args: {
            "access_token": "fresh",
            "refresh_token": "refresh-test",
            "expires_at": time.time() + 3600,
        },
    )
    monkeypatch.setattr("ghealth.api.client.save_tokens", saved.append)

    def handle(request):
        assert request.headers["Authorization"] == "Bearer fresh"
        return httpx.Response(200, json={"name": "users/me/identity", "healthUserId": "example-user"})

    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="https://health.googleapis.com"
    ) as http:
        result = call(
            create_server(client_factory=lambda: create_authenticated_client(client=http)),
            "get_user",
            {"resource": "identity"},
        )
    assert result.structured_content == {"name": "users/me/identity", "healthUserId": "example-user"}
    assert saved[0]["access_token"] == "fresh"


def test_client_configs() -> None:
    import tomllib

    runner = CliRunner()
    for client in ("codex", "cursor", "claude"):
        result = runner.invoke(app, ["config", "--client", client])
        assert result.exit_code == 0, result.output
        if client == "codex":
            entry = tomllib.loads(result.stdout)["mcp_servers"]["ghealth"]
        else:
            entry = json.loads(result.stdout)["mcpServers"]["ghealth"]
        assert entry["command"] == sys.executable
        assert entry["args"] == ["-m", "ghealth.mcp_cli"]


def test_default_launcher_is_readonly(monkeypatch) -> None:
    flags = []

    class FakeServer:
        def run(self):
            pass

    def create(**kwargs):
        flags.append(kwargs["allow_writes"])
        return FakeServer()

    monkeypatch.setattr("ghealth.server.create_server", create)
    assert CliRunner().invoke(app, []).exit_code == 0
    assert flags == [False]


def test_real_stdio_handshake_and_tool_call(tmp_path) -> None:
    async def exercise():
        # No Google credentials required for initialization or catalog discovery.
        params = StdioServerParameters(command=sys.executable, args=["-m", "ghealth.mcp_cli"], cwd=tmp_path)
        with anyio.fail_after(30):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.server_info.name == "ghealth-mcp"
                tools = await session.list_tools()
                assert len(tools.tools) == 10
                result = await session.call_tool("list_data_types", {})
                assert not result.is_error
                assert result.structured_content["dataTypes"]
                invalid = await session.call_tool("list_data_points", {"data_type": "../profile"})
                assert invalid.is_error

    anyio.run(exercise)


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_opt_in_mutations_use_documented_paths(operation) -> None:
    seen = []
    payload = {"steps": {"count": "42"}}

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={} if operation == "delete" else payload)

    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="https://health.googleapis.com"
    ) as http:
        server = create_server(
            allow_writes=True,
            client_factory=lambda: GHealthApiClient(
                Config(client_id="test", client_secret="test"),
                {"access_token": "test-access"},
                client=http,
            ),
        )
        arguments: dict = {"data_type": "steps"}
        if operation == "delete":
            arguments["data_point_ids"] = ["abc"]
            result = call(server, "delete_data_points", arguments)
            assert seen[0].url.path.endswith("/steps/dataPoints:batchDelete")
            assert json.loads(seen[0].content) == {"names": ["users/me/dataTypes/steps/dataPoints/abc"]}
        else:
            arguments["data_point"] = payload
            if operation == "update":
                arguments.update(data_point_id="abc", update_mask="steps.count")
            result = call(server, f"{operation}_data_point", arguments)
            assert seen[0].method == ("POST" if operation == "create" else "PATCH")
            assert json.loads(seen[0].content) == payload
        assert not result.is_error


def test_tcx_is_returned_as_xml() -> None:
    xml = '<?xml version="1.0"?><TrainingCenterDatabase/>'

    def handle(request):
        assert request.url.path.endswith("/exercise/dataPoints/abc:exportExerciseTcx")
        assert request.url.params["alt"] == "media"
        return httpx.Response(200, text=xml)

    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="https://health.googleapis.com"
    ) as http:
        server = create_server(
            client_factory=lambda: GHealthApiClient(
                Config(client_id="test", client_secret="test"),
                {"access_token": "test-access"},
                client=http,
            )
        )
        result = call(server, "export_exercise_tcx", {"data_point_id": "abc"})
        assert result.content[0].text == xml
