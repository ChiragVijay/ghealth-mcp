"""Register the installed server without asking users to hand-edit agent config."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from ghealth.local_files import write_private_file

AgentClient = Literal["codex", "cursor", "claude", "claude-desktop"]


def server_command() -> list[str]:
    """Use an absolute interpreter path so GUI apps do not depend on shell PATH."""
    return [str(Path(sys.executable).resolve()), "-m", "ghealth.mcp_cli"]


def register_client(client: AgentClient) -> str:
    """Register only ghealth, preserving other servers and agent settings."""
    command = server_command()
    if client in {"codex", "claude"}:
        executable = shutil.which(client)
        if executable is None:
            raise RuntimeError(
                f"{client} was not found. Install it, then run ghealth-mcp connect --client {client}."
            )
        lookup = [executable, "mcp", "get", "ghealth"]
        if client == "codex":
            lookup.append("--json")
        existing = subprocess.run(lookup, capture_output=True, text=True, check=False, timeout=30)  # noqa: S603
        if existing.returncode == 0:
            if client == "codex":
                registered = json.loads(existing.stdout).get("transport", {})
                if registered.get("command") != command[0] or registered.get("args", []) != command[1:]:
                    raise ValueError(
                        "A different ghealth server is registered in Codex. Existing settings were kept."
                    )
            return f"ghealth is already registered with {client}. Existing settings were kept."
        arguments = [executable, "mcp", "add"]
        if client == "claude":
            arguments += ["--transport", "stdio", "--scope", "user"]
        arguments += ["ghealth", "--", *command]
        result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=30)  # noqa: S603
        if result.returncode:
            raise RuntimeError(
                f"Could not register ghealth with {client}. Your Google sign-in is saved. "
                f"Run ghealth-mcp config --client {client} for manual configuration."
            )
        return f"Connected to {client}. Restart or reconnect the agent to load its tools."

    if client == "cursor":
        path = Path.home() / ".cursor" / "mcp.json"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is missing. Use ghealth-mcp config --client claude for manual setup.")
        path = Path(appdata) / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        raise RuntimeError(
            "Use ghealth-mcp config --client claude to configure your Claude Desktop installation."
        )

    document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(document, dict) or not isinstance(document.get("mcpServers", {}), dict):
        raise TypeError(f"Invalid MCP configuration at {path}. The file has not been changed.")
    entry: dict = {"command": command[0], "args": command[1:]}
    if client == "cursor":
        entry["type"] = "stdio"
    existing = document.setdefault("mcpServers", {}).get("ghealth")
    if existing == entry:
        return f"Already connected to {client}. Configuration: {path}"
    if existing is not None:
        raise ValueError(
            f"A different ghealth server already exists in {path}. "
            f"Use ghealth-mcp config --client {client} to review the new configuration."
        )
    document["mcpServers"]["ghealth"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep a backup before editing an existing user file.
    if path.exists():
        write_private_file(
            path.with_suffix(path.suffix + ".ghealth-backup"), path.read_text(encoding="utf-8")
        )
    write_private_file(path, json.dumps(document, indent=2) + "\n")
    return f"Connected to {client}. Restart the app to load its tools. Configuration: {path}"
