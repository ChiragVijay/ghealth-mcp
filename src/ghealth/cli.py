import typer

from ghealth.api import create_authenticated_client
from ghealth.auth.oauth import refresh_access_token, revoke_token
from ghealth.commands.agent import app as agent_app
from ghealth.commands.auth import app as auth_app
from ghealth.commands.context import CliState
from ghealth.commands.data_points import app as data_points_app
from ghealth.commands.data_types import app as data_types_app
from ghealth.commands.shortcuts import SHORTCUT_APPS
from ghealth.commands.users_devices import devices_app, user_app
from ghealth.commands.webhooks import subscribers_app, subscriptions_app
from ghealth.output import FormatEnum

app = typer.Typer(help="G Health CLI tool")

app.add_typer(agent_app)
app.add_typer(data_types_app, name="data-types")
app.add_typer(auth_app, name="auth")
app.add_typer(user_app, name="user")
app.add_typer(devices_app, name="devices")
app.add_typer(data_points_app, name="data-points")
app.add_typer(subscribers_app, name="subscribers")
app.add_typer(subscriptions_app, name="subscriptions")
for shortcut_name, shortcut_app in SHORTCUT_APPS:
    app.add_typer(shortcut_app, name=shortcut_name)


@app.command(name="update")
def update_cmd() -> None:
    """Update the CLI tool to the latest version."""
    import shutil
    import subprocess

    uv_path = shutil.which("uv")
    if not uv_path:
        typer.echo("Error: 'uv' package manager could not be located in your PATH.", err=True)
        typer.echo("This CLI tool requires 'uv' to perform updates.", err=True)
        typer.echo(
            "Please install uv (https://astral.sh/uv) or run manually: uv tool upgrade ghealth-mcp", err=True
        )
        raise typer.Exit(code=1)

    typer.echo("Found 'uv'. Running `uv tool upgrade ghealth-mcp`...")
    try:
        result = subprocess.run([uv_path, "tool", "upgrade", "ghealth-mcp"], check=True)  # noqa: S603
        if result.returncode == 0:
            typer.echo("ghealth updated successfully!")
            return
    except subprocess.CalledProcessError as e:
        typer.echo(f"Error during update: {e}", err=True)
        typer.echo("Please try running manually: uv tool upgrade ghealth-mcp", err=True)
        raise typer.Exit(code=1) from None


def version_callback(value: bool) -> None:
    if value:
        import importlib.metadata

        try:
            version = importlib.metadata.version("ghealth-mcp")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        typer.echo(message=f"ghealth version: {version}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    output_format: FormatEnum = typer.Option(FormatEnum.TABLE, "--format", help="Output format"),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Quiet output (suppress non-error console output)",
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable color output"),
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    state = CliState(
        output_format=output_format,
        quiet=quiet,
        debug=debug,
        no_color=no_color,
        create_authenticated_client_func=create_authenticated_client,
        refresh_access_token_func=refresh_access_token,
        revoke_token_func=revoke_token,
    )
    ctx.obj = state


if __name__ == "__main__":
    app()
