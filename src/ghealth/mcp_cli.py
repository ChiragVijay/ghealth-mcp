"""Small local launcher: setup once, then let an MCP host run the server."""

import json
import subprocess
import sys
from pathlib import Path

import httpx
import typer

from ghealth.api.client import create_authenticated_client
from ghealth.auth.oauth import revoke_token
from ghealth.auth.token_store import delete_tokens, load_tokens
from ghealth.config import get_config_dir, load_config
from ghealth.integrations import AgentClient, register_client
from ghealth.setup import configure_desktop, login_desktop

app = typer.Typer(no_args_is_help=False, help="Google Health MCP. Run setup once; no arguments starts stdio.")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        serve(allow_writes=False)


@app.command()
def serve(
    allow_writes: bool = typer.Option(False, "--allow-writes", help="Expose health data mutation tools."),
) -> None:
    """Start the local MCP server on stdio. No browser or prompts at startup."""
    from ghealth.server import create_server

    create_server(allow_writes=allow_writes).run()


@app.command()
def setup(
    credentials: Path | None = typer.Option(
        None, "--credentials", "-c", help="Downloaded Desktop OAuth JSON."
    ),
    scope_profile: str = typer.Option("readonly", help="OAuth scope profile; readonly by default."),
    scopes: str | None = typer.Option(None, help="Additional comma-separated scope aliases or URLs."),
    client: AgentClient | None = typer.Option(
        None, "--client", help="Also connect codex, cursor, claude, or claude-desktop."
    ),
) -> None:
    """Save credentials and sign in through your browser. Reuses existing ghealth configuration."""
    try:
        config = configure_desktop(credentials) if credentials else load_config()
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if config is None:
        typer.echo("Run ghealth-mcp setup --credentials /path/to/desktop-client.json first.", err=True)
        raise typer.Exit(1)
    try:
        typer.echo(
            "Google Health data is returned to your connected agent and its model provider. "
            "OAuth tokens stay on this computer. "
            "Approve the requested access in Google's browser consent screen."
        )
        login_desktop(
            config,
            scope_profile=scope_profile,
            extra_scopes=scopes,
            show_url=lambda url: typer.echo(f"Open in browser:\n{url}"),
        )
        _verify_connection()
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("Google Health connection verified. Your sign-in is saved for all local agents.")
    if client:
        connect(client)
    else:
        typer.echo("Next: ghealth-mcp connect --client codex (or cursor, claude, claude-desktop).")


def _verify_connection() -> None:
    client = create_authenticated_client()
    try:
        client.get_identity()
    finally:
        client.close()


@app.command()
def connect(
    client: AgentClient = typer.Option(
        ..., "--client", help="codex, cursor, claude (Code), or claude-desktop."
    ),
) -> None:
    """Connect an agent automatically using saved Google sign-in. No config copying required."""
    try:
        message = register_client(client)
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(message)


@app.command()
def status() -> None:
    """Verify stored credentials against Google (refreshing expired access tokens)."""
    try:
        _verify_connection()
    except RuntimeError as exc:
        typer.echo(f"Not connected: {exc}\nRun ghealth-mcp setup to sign in.", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Connected to Google Health. Configuration: {get_config_dir()}")


@app.command()
def logout() -> None:
    """Revoke Google's grant and remove local tokens. All local agents share this sign-in."""
    config = load_config()
    tokens = load_tokens()
    try:
        if config and tokens and (token := tokens.get("refresh_token") or tokens.get("access_token")):
            revoke_token(config, token)
    except httpx.HTTPError as exc:
        typer.echo("Google revocation failed. Local tokens were kept so you can retry logout.", err=True)
        raise typer.Exit(1) from exc
    try:
        delete_tokens()
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("Local tokens removed. Run setup to sign in again.")


@app.command(name="config")
def client_config(
    client: AgentClient = typer.Option(..., "--client"),
) -> None:
    """Print configuration using this installation's absolute Python path. Contains no secrets."""
    command = str(Path(sys.executable).resolve())
    args = ["-m", "ghealth.mcp_cli"]
    if client == "codex":
        typer.echo(f"[mcp_servers.ghealth]\ncommand = {json.dumps(command)}\nargs = {json.dumps(args)}")
    else:
        entry: dict = {"command": command, "args": args}
        if client == "cursor":
            entry["type"] = "stdio"
        typer.echo(json.dumps({"mcpServers": {"ghealth": entry}}, indent=2))


if __name__ == "__main__":
    app()
