import json

from typer.testing import CliRunner

from ghealth.cli import app

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "G Health CLI tool" in result.stdout


def test_version() -> None:
    import importlib.metadata

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    expected_version = importlib.metadata.version("ghealth-mcp")
    assert f"ghealth version: {expected_version}" in result.stdout


def test_console_entry_point_imports() -> None:
    from ghealth.cli import app as imported_app

    assert imported_app is app


def test_api_public_imports_remain_available() -> None:
    from ghealth.api import (
        GHealthApiClient,
        GHealthApiError,
        build_civil_datetime,
        build_data_point_time_filter,
    )

    assert GHealthApiClient.__name__ == "GHealthApiClient"
    assert GHealthApiError.__name__ == "GHealthApiError"
    assert callable(build_civil_datetime)
    assert callable(build_data_point_time_filter)


def test_shortcut_commands_appear_in_root_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "steps",
        "sleep",
        "heart-rate",
        "calories",
        "active-energy",
        "active-minutes",
        "active-zone-minutes",
        "distance",
        "floors",
        "exercise",
        "weight",
        "height",
        "body-fat",
        "hydration",
        "food",
        "nutrition",
    ):
        assert command in result.stdout


def test_data_types_list_table() -> None:
    result = runner.invoke(app, ["data-types", "list"])
    assert result.exit_code == 0
    assert "G Health Data Types" in result.stdout
    assert "steps" in result.stdout


def test_data_types_list_json() -> None:
    result = runner.invoke(app, ["--format", "json", "data-types", "list"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 41
    # Check one element
    steps_item = next(item for item in data if item["data_type"] == "steps")
    assert steps_item["display_name"] == "Steps"


def test_data_types_list_raw() -> None:
    result = runner.invoke(app, ["--format", "raw", "data-types", "list"])
    assert result.exit_code == 0
    lines = result.stdout.strip().split("\n")
    assert len(lines) == 41
    assert "steps" in lines


def test_data_types_describe_valid_table() -> None:
    result = runner.invoke(app, ["data-types", "describe", "steps"])
    assert result.exit_code == 0
    assert "Data Type: Steps" in result.stdout


def test_data_types_describe_valid_json() -> None:
    result = runner.invoke(app, ["--format", "json", "data-types", "describe", "steps"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["data_type"] == "steps"
    assert data["display_name"] == "Steps"


def test_data_types_describe_valid_raw() -> None:
    result = runner.invoke(app, ["--format", "raw", "data-types", "describe", "steps"])
    assert result.exit_code == 0
    assert "Display Name: Steps" in result.stdout


def test_data_types_describe_invalid_table() -> None:
    result = runner.invoke(app, ["data-types", "describe", "invalid-type"])
    assert result.exit_code == 2
    assert "Error: Data type 'invalid-type' not found in registry." in result.stdout


def test_data_types_describe_invalid_json() -> None:
    result = runner.invoke(app, ["--format", "json", "data-types", "describe", "invalid-type"])
    assert result.exit_code == 2
    data = json.loads(result.stdout)
    assert "error" in data
    assert data["error"]["code"] == "data_type_not_found"


def test_data_types_operations() -> None:
    result = runner.invoke(app, ["data-types", "operations", "steps"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "get" in result.stdout


def test_data_types_scopes() -> None:
    result = runner.invoke(app, ["data-types", "scopes", "steps"])
    assert result.exit_code == 0
    assert "activity_and_fitness.readonly" in result.stdout


def test_global_flags_quiet() -> None:
    result = runner.invoke(app, ["--quiet", "data-types", "list"])
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_global_flags_no_color() -> None:
    result = runner.invoke(app, ["--no-color", "data-types", "list"])
    assert result.exit_code == 0
    assert "steps" in result.stdout


def test_data_types_operations_invalid_table() -> None:
    result = runner.invoke(app, ["data-types", "operations", "invalid-type"])
    assert result.exit_code == 2
    assert "Error: Data type 'invalid-type' not found in registry." in result.stdout


def test_data_types_operations_invalid_json() -> None:
    result = runner.invoke(app, ["--format", "json", "data-types", "operations", "invalid-type"])
    assert result.exit_code == 2
    data = json.loads(result.stdout)
    assert "error" in data
    assert data["error"]["code"] == "data_type_not_found"


def test_data_types_operations_json() -> None:
    result = runner.invoke(app, ["--format", "json", "data-types", "operations", "steps"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "list" in data
    assert "get" in data


def test_data_types_scopes_invalid_table() -> None:
    result = runner.invoke(app, ["data-types", "scopes", "invalid-type"])
    assert result.exit_code == 2
    assert "Error: Data type 'invalid-type' not found in registry." in result.stdout


def test_data_types_scopes_invalid_json() -> None:
    result = runner.invoke(app, ["--format", "json", "data-types", "scopes", "invalid-type"])
    assert result.exit_code == 2
    data = json.loads(result.stdout)
    assert "error" in data
    assert data["error"]["code"] == "data_type_not_found"


def test_data_types_scopes_json() -> None:
    result = runner.invoke(app, ["--format", "json", "data-types", "scopes", "steps"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert any("activity_and_fitness.readonly" in s for s in data)


def test_update_command_uv(monkeypatch) -> None:
    import shutil
    import subprocess

    uv_runs = []

    def mock_which(cmd):
        if cmd == "uv":
            return "/mocked/path/to/uv"
        return None

    def mock_run(cmd, *args, **kwargs):
        uv_runs.append(cmd)

        class MockResult:
            returncode = 0

        return MockResult()

    monkeypatch.setattr(shutil, "which", mock_which)
    monkeypatch.setattr(subprocess, "run", mock_run)

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "Found 'uv'" in result.stdout
    assert "ghealth updated successfully!" in result.stdout
    assert uv_runs == [["/mocked/path/to/uv", "tool", "upgrade", "ghealth-mcp"]]


def test_update_command_not_found(monkeypatch) -> None:
    import shutil

    def mock_which(cmd):
        return None

    monkeypatch.setattr(shutil, "which", mock_which)

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "Error: 'uv' package manager could not be located in your PATH." in result.stderr
    assert "This CLI tool requires 'uv' to perform updates." in result.stderr
