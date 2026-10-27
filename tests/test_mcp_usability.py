import anyio
import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from ghealth.api.client import GHealthApiClient
from ghealth.config import Config
from ghealth.server import create_server


def call(server: MCPServer, tool: str, arguments: dict) -> CallToolResult:
    result = anyio.run(server.call_tool, tool, arguments)
    assert isinstance(result, CallToolResult)
    return result


@pytest.mark.parametrize(
    ("data_type", "field"),
    [
        ("exercise", "exercise.interval.civil_start_time"),
        ("sleep", "sleep.interval.civil_end_time"),
        ("steps", "steps.interval.civil_start_time"),
        ("weight", "weight.sample_time.civil_time"),
    ],
)
@pytest.mark.parametrize("tool", ["list_data_points", "reconcile_data_points"])
def test_models_can_use_dates_without_writing_filter_syntax(data_type, field, tool) -> None:
    def handler(request):
        assert request.url.params["filter"] == f'{field} >= "2026-10-20" AND {field} < "2026-10-27"'
        assert request.url.params["pageToken"] == "next-page"
        return httpx.Response(200, json={"dataPoints": [], "nextPageToken": "another-page"})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://health.googleapis.com"
    ) as http:
        server = create_server(
            client_factory=lambda: GHealthApiClient(
                Config(client_id="id", client_secret="secret"),
                {"access_token": "test-access"},
                client=http,
            )
        )
        result = call(
            server,
            tool,
            {
                "data_type": data_type,
                "start_date": "2026-10-20",
                "end_date": "2026-10-27",
                "page_token": "next-page",
            },
        )
        assert result.structured_content == {"dataPoints": [], "nextPageToken": "another-page"}


@pytest.mark.parametrize(
    "arguments",
    [
        {"start_date": "2026-10-20"},
        {"start_date": "2026-10-27", "end_date": "2026-10-20"},
        {"start_date": "2026-02-30", "end_date": "2026-03-01"},
        {"start_date": "20261020", "end_date": "2026-10-27"},
        {"start_date": "2026-10-20", "end_date": "2026-10-27", "filter": "custom"},
        {"page_size": 26},
    ],
)
def test_bad_date_or_session_page_inputs_fail_before_google(arguments) -> None:
    def fail():
        pytest.fail("Invalid input must not create an API client")

    with pytest.raises(ToolError):
        anyio.run(
            create_server(client_factory=fail).call_tool,
            "list_data_points",
            {
                "data_type": "sleep",
                **arguments,
            },
        )


def test_catalog_search_reduces_discovery_output() -> None:
    server = create_server()
    result = call(server, "list_data_types", {"query": " SLEEP "})
    assert result.structured_content is not None
    rows = result.structured_content["dataTypes"]
    assert 0 < len(rows) < 41
    assert any(row["data_type"] == "sleep" for row in rows)
    assert call(server, "list_data_types", {"query": "unknown-metric"}).structured_content == {
        "dataTypes": [],
    }


@pytest.mark.parametrize(
    ("tool", "arguments", "path"),
    [
        (
            "get_data_point",
            {"data_type": "exercise", "data_point_id": "users/actual-user/dataTypes/exercise/dataPoints/abc"},
            "/v4/users/me/dataTypes/exercise/dataPoints/abc",
        ),
        (
            "get_paired_device",
            {"device_id": "users/actual-user/pairedDevices/abc"},
            "/v4/users/me/pairedDevices/abc",
        ),
    ],
)
def test_detail_tools_accept_names_directly_from_google(tool, arguments, path) -> None:
    def handler(request):
        assert request.url.path == path
        return httpx.Response(200, json={"name": path.removeprefix("/v4/")})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://health.googleapis.com"
    ) as http:
        server = create_server(
            client_factory=lambda: GHealthApiClient(
                Config(client_id="id", client_secret="secret"),
                {"access_token": "test-access"},
                client=http,
            )
        )
        assert not call(server, tool, arguments).is_error


@pytest.mark.parametrize(
    "reference",
    [
        "users/me/dataTypes/weight/dataPoints/abc",
        "../profile",
        "https://example.com/abc",
        "users/me/dataTypes/sleep/dataPoints/../profile",
    ],
)
def test_full_names_must_match_collection_and_cannot_traverse(reference) -> None:
    def fail():
        pytest.fail("Invalid reference must not create a client")

    with pytest.raises(ToolError):
        anyio.run(
            create_server(client_factory=fail).call_tool,
            "get_data_point",
            {
                "data_type": "sleep",
                "data_point_id": reference,
            },
        )
