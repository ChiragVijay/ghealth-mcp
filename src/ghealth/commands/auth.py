import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx
import typer
from rich import box
from rich.table import Table

from ghealth.auth.oauth import (
    exchange_code_for_tokens,
    extract_code_from_input,
    generate_pkce,
    run_local_redirect_server,
)
from ghealth.auth.scopes import get_scopes_for_login
from ghealth.auth.token_store import delete_tokens, load_tokens, save_tokens
from ghealth.commands.context import CliState
from ghealth.config import Config, load_config, parse_credentials_json, save_config
from ghealth.output import FormatEnum, console, emit_json, emit_raw_lines, print_cli_error

app = typer.Typer(help="Manage authentication for G Health CLI")


@app.command(name="configure")
def auth_configure(
    ctx: typer.Context,
    credentials: Path | None = typer.Option(
        None, "--credentials", "-c", help="Path to Google Cloud OAuth client secret credentials JSON file."
    ),
    token_storage: str | None = typer.Option(
        None,
        "--token-storage",
        help="Token storage backend: 'auto' (default, keyring + file fallback), 'keyring', or 'plaintext'.",
    ),
    i_understand_health_data_risk: bool = typer.Option(
        False,
        "--i-understand-health-data-risk",
        help="Acknowledge the risk of storing health token data in plaintext.",
    ),
) -> None:
    """Configure G Health CLI OAuth client credentials and token storage settings."""
    state: CliState = ctx.obj

    # 1. Handle token_storage option validation
    storage = None
    if token_storage is not None:
        if token_storage not in ("auto", "keyring", "plaintext"):
            print_cli_error(
                state,
                "invalid_storage_backend",
                "Storage backend must be 'auto', 'keyring', or 'plaintext'.",
                exit_code=2,
            )
        if token_storage == "plaintext" and not i_understand_health_data_risk:
            print_cli_error(
                state,
                "risk_acknowledgement_required",
                "To configure plaintext storage, explicitly acknowledge the risk by passing "
                "the --i-understand-health-data-risk flag.",
                exit_code=2,
            )
        storage = token_storage

    # 2. Handle credentials option
    client_id = None
    client_secret = None
    auth_uri = "https://accounts.google.com/o/oauth2/auth"
    token_uri = "https://oauth2.googleapis.com/token"

    if credentials is not None:
        try:
            creds_data = parse_credentials_json(credentials)
            client_id = creds_data["client_id"]
            client_secret = creds_data["client_secret"]
            auth_uri = creds_data["auth_uri"]
            token_uri = creds_data["token_uri"]
        except Exception as e:
            print_cli_error(
                state,
                "invalid_credentials",
                f"Failed to parse credentials: {e}",
                exit_code=2,
            )

    # Load existing config or start new one
    existing_config = load_config()

    # We must have either existing config or credentials file to configure
    if not existing_config and not credentials:
        print_cli_error(
            state,
            "missing_credentials",
            "Please provide a credentials file using the --credentials option to initialize configuration.",
            exit_code=2,
        )

    # Build updated config
    updated_client_id = client_id or (existing_config.client_id if existing_config else None)
    updated_client_secret = client_secret or (existing_config.client_secret if existing_config else None)

    if not updated_client_id or not updated_client_secret:
        print_cli_error(
            state,
            "incomplete_configuration",
            "Client ID and client secret are missing. Provide a valid credentials file.",
            exit_code=2,
        )

    new_config = Config(
        client_id=updated_client_id,
        client_secret=updated_client_secret,
        token_storage=storage or (existing_config.token_storage if existing_config else "auto"),
        auth_uri=auth_uri
        or (existing_config.auth_uri if existing_config else "https://accounts.google.com/o/oauth2/auth"),
        token_uri=token_uri
        or (existing_config.token_uri if existing_config else "https://oauth2.googleapis.com/token"),
        user_email=existing_config.user_email if existing_config else None,
    )

    save_config(new_config)

    if state.output_format == FormatEnum.JSON:
        if not state.quiet:
            emit_json(
                {
                    "configured": True,
                    "token_storage_backend": new_config.token_storage,
                    "client_id": new_config.client_id,
                },
            )
    elif not state.quiet:
        console.print(
            "[green]Success:[/green] Configuration saved successfully. "
            f"Token storage: [cyan]{new_config.token_storage}[/cyan]",
        )


@app.command(name="login")
def auth_login(
    ctx: typer.Context,
    scope_profile: str | None = typer.Option(
        None,
        "--scope-profile",
        help="Scope profile: 'readonly', 'all-read', 'activity', 'sleep', 'nutrition', 'metrics', 'write'.",
    ),
    scopes: str | None = typer.Option(
        None,
        "--scopes",
        help=(
            "Comma-separated extra OAuth scopes or aliases. Merged with --scope-profile when both are passed."
        ),
    ),
    with_webhooks: bool = typer.Option(
        False,
        "--with-webhooks",
        help="Also request Google Cloud scope for webhook subscriber/subscription management.",
    ),
    manual: bool = typer.Option(
        False,
        "--manual",
        help="Force manual authentication fallback (copy/paste code).",
    ),
    accept_disclosure: bool = typer.Option(
        False,
        "--accept-disclosure",
        help="Accept the data privacy disclosure in non-interactive environments.",
    ),
) -> None:
    """Log in and authorize the CLI with your Google Account."""
    state: CliState = ctx.obj

    config = load_config()
    if not config:
        print_cli_error(
            state,
            "not_configured",
            "CLI is not configured. Please run 'ghealth auth configure --credentials <path>' first.",
            exit_code=3,
        )

    effective_scope_profile = scope_profile
    effective_scopes = scopes
    if with_webhooks:
        effective_scope_profile = effective_scope_profile or "readonly"
        effective_scopes = "cloud-platform" if not effective_scopes else f"{effective_scopes},cloud-platform"

    try:
        resolved_scopes = get_scopes_for_login(effective_scope_profile, effective_scopes)
    except ValueError as e:
        print_cli_error(state, "invalid_scope_profile", str(e), exit_code=2)

    disclosure_msg = (
        "ghealth accesses your Google Health data only to show it locally in this CLI.\n"
        "Data is not sent to this project. "
        "Tokens use your configured local file and/or OS credential store.\n"
        f"Requested scopes: {', '.join(resolved_scopes)}"
    )

    is_non_interactive = os.environ.get("GHEALTH_NONINTERACTIVE") == "1" or not sys.stdin.isatty()

    if is_non_interactive:
        if not accept_disclosure:
            print_cli_error(
                state,
                "disclosure_not_accepted",
                "You must accept the privacy disclosure in non-interactive mode using "
                "the --accept-disclosure flag.",
                exit_code=2,
            )
    else:
        if not state.quiet:
            console.print("[yellow]Privacy Disclosure:[/yellow]")
            console.print(disclosure_msg)
            console.print("")
        accept = typer.confirm("Do you accept this disclosure and wish to proceed?")
        if not accept:
            print_cli_error(
                state,
                "disclosure_rejected",
                "Authentication aborted because privacy disclosure was not accepted.",
                exit_code=1,
            )

    code_verifier, code_challenge = generate_pkce()
    oauth_state = secrets.token_urlsafe(16)

    code = None
    redirect_uri = None

    if manual:
        redirect_uri = "https://www.google.com"
    else:
        try:
            server, actual_port = run_local_redirect_server()
            server.expected_state = oauth_state
            redirect_uri = f"http://localhost:{actual_port}"
        except Exception as e:
            if not state.quiet:
                console.print(
                    "[yellow]Warning:[/yellow] Could not start local redirect server "
                    f"({e}). Falling back to manual mode.",
                )
            manual = True
            redirect_uri = "https://www.google.com"

    auth_url = (
        f"{config.auth_uri}?"
        f"client_id={config.client_id}&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"response_type=code&"
        f"scope={urllib.parse.quote(' '.join(resolved_scopes))}&"
        f"state={oauth_state}&"
        f"code_challenge={code_challenge}&"
        f"code_challenge_method=S256&"
        f"access_type=offline&"
        f"prompt=consent"
    )

    if not state.quiet:
        console.print(
            "\nOpening browser for authentication. If the browser does not open automatically, "
            "please open the following URL in your browser:",
        )
        console.print(f"[link={auth_url}]{auth_url}[/link]\n")

    if not manual:
        webbrowser.open(auth_url)

        if not state.quiet:
            console.print("Waiting for browser redirect callback...")
        try:
            start_time = time.time()
            while time.time() - start_time < 300:
                server.handle_request()
                if not server.code_queue.empty():
                    code, returned_state = server.code_queue.get()
                    if returned_state != oauth_state:
                        print_cli_error(
                            state,
                            "oauth_state_mismatch",
                            "OAuth state mismatch. The authentication request may have been tampered with.",
                            exit_code=1,
                        )
                    break
            else:
                print_cli_error(
                    state,
                    "oauth_timeout",
                    "Authentication timed out waiting for redirect callback.",
                    exit_code=1,
                )
        except KeyboardInterrupt:
            print_cli_error(state, "oauth_aborted", "Authentication aborted by user.", exit_code=1)
        finally:
            server.server_close()
    else:
        if not state.quiet:
            console.print("1. Log in via your browser using the URL above.")
            console.print(
                "2. Once authorized, copy the entire browser destination URL "
                "(or the 'code' parameter value).",
            )
        try:
            user_input = typer.prompt("Paste the URL or code here")
            code = extract_code_from_input(user_input)
            if not code:
                print_cli_error(
                    state,
                    "invalid_code",
                    "No authorization code found in input.",
                    exit_code=2,
                )
        except (KeyboardInterrupt, typer.Abort):
            print_cli_error(state, "oauth_aborted", "Authentication aborted by user.", exit_code=1)

    if not code:
        print_cli_error(state, "invalid_code", "No authorization code found.", exit_code=1)

    try:
        token_data = exchange_code_for_tokens(config, code, code_verifier, redirect_uri)
    except Exception as e:
        print_cli_error(state, "exchange_failed", f"Failed to exchange authorization code: {e}", exit_code=1)

    try:
        userinfo_resp = httpx.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            timeout=5.0,
        )
        if userinfo_resp.status_code == 200:
            config.user_email = userinfo_resp.json().get("email")
            save_config(config)
    except Exception:
        pass

    try:
        save_tokens(token_data)
    except Exception as e:
        print_cli_error(state, "token_save_failed", str(e), exit_code=1)

    if state.output_format == FormatEnum.JSON:
        if not state.quiet:
            emit_json(
                {
                    "authenticated": True,
                    "account": config.user_email or "unknown",
                    "token_storage_backend": config.token_storage,
                    "scopes": token_data.get("scope", "").split(),
                    "expires_at": token_data.get("expires_at"),
                },
            )
    elif not state.quiet:
        console.print("[green]Success:[/green] Login successful. Tokens saved securely.")


@app.command(name="status")
def auth_status(ctx: typer.Context) -> None:
    """Show current authentication status, scopes, and token details."""
    state: CliState = ctx.obj

    config = load_config()
    if not config:
        print_cli_error(
            state,
            "not_configured",
            "CLI is not configured. Please run 'ghealth auth configure' first.",
            exit_code=3,
        )

    tokens = load_tokens()
    if not tokens:
        print_cli_error(
            state,
            "not_authenticated",
            "Not logged in. Please run 'ghealth auth login'.",
            exit_code=3,
        )

    expires_at = tokens.get("expires_at", 0)
    now = int(time.time())
    expired = now >= expires_at
    expires_in = max(0, expires_at - now)

    expiry_str = (
        f"Expired (at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))})"
        if expired
        else f"Expires in {expires_in} seconds"
    )

    status_data = {
        "account": config.user_email or "unknown",
        "scopes": tokens.get("scope", "").split(" "),
        "expiry": expiry_str,
        "expires_at": expires_at,
        "token_storage_backend": config.token_storage,
        "configured_client_id": config.client_id,
        "authenticated": True,
    }

    if state.output_format in (FormatEnum.JSON, FormatEnum.RAW):
        if not state.quiet:
            emit_json(status_data)
    elif not state.quiet:
        table = Table(
            title="[bold blue]Authentication Status[/bold blue]",
            show_header=False,
            box=box.ROUNDED,
        )
        table.add_column("Property", style="cyan", justify="right")
        table.add_column("Value", style="white")
        status_text = "[green]Authenticated[/green]" if not expired else "[red]Authenticated (Expired)[/red]"
        table.add_row("Status", status_text)
        table.add_row("Account", f"[yellow]{status_data['account']}[/yellow]")
        table.add_row("Storage Backend", status_data["token_storage_backend"])
        table.add_row("Client ID", status_data["configured_client_id"])
        table.add_row("Expiry", f"[magenta]{expiry_str}[/magenta]")
        table.add_row("Scopes", "\n".join(status_data["scopes"]))
        console.print(table)


@app.command(name="scopes")
def auth_scopes(ctx: typer.Context) -> None:
    """List OAuth scopes currently authorized for the CLI."""
    state: CliState = ctx.obj

    tokens = load_tokens()
    if not tokens:
        print_cli_error(
            state,
            "not_authenticated",
            "Not logged in. Please run 'ghealth auth login'.",
            exit_code=3,
        )

    scopes_list = tokens.get("scope", "").split(" ")

    if state.output_format == FormatEnum.JSON:
        if not state.quiet:
            emit_json(scopes_list)
    elif state.output_format == FormatEnum.RAW:
        if not state.quiet:
            emit_raw_lines(scopes_list)
    elif not state.quiet:
        table = Table(title="Authorized Scopes")
        table.add_column("Scope URL", style="green")
        for s in scopes_list:
            table.add_row(s)
        console.print(table)


@app.command(name="refresh")
def auth_refresh(ctx: typer.Context) -> None:
    """Force refresh of the OAuth access token."""
    state: CliState = ctx.obj

    config = load_config()
    if not config:
        print_cli_error(
            state,
            "not_configured",
            "CLI is not configured. Please run 'ghealth auth configure' first.",
            exit_code=3,
        )

    tokens = load_tokens()
    if not tokens or "refresh_token" not in tokens:
        print_cli_error(
            state,
            "not_authenticated",
            "Not logged in or refresh token is missing. Please run 'ghealth auth login'.",
            exit_code=3,
        )

    try:
        new_tokens = state.refresh_access_token(config, tokens["refresh_token"])
        save_tokens(new_tokens)
    except Exception as e:
        print_cli_error(state, "refresh_failed", f"Failed to refresh access token: {e}", exit_code=3)

    if state.output_format == FormatEnum.JSON:
        if not state.quiet:
            emit_json(
                {
                    "refreshed": True,
                    "expires_at": new_tokens.get("expires_at"),
                    "scopes": new_tokens.get("scope", "").split(),
                },
            )
    elif not state.quiet:
        console.print("[green]Success:[/green] Access token refreshed successfully.")


@app.command(name="logout")
def auth_logout(ctx: typer.Context) -> None:
    """Log out and delete local authentication tokens."""
    state: CliState = ctx.obj

    try:
        delete_tokens()
    except RuntimeError:
        print_cli_error(
            state, "logout_failed", "Local credentials could not be cleared. Retry logout.", exit_code=1
        )

    if state.output_format == FormatEnum.JSON:
        if not state.quiet:
            emit_json({"logged_out": True})
    elif not state.quiet:
        console.print("[green]Success:[/green] Logged out successfully. Local tokens have been deleted.")


@app.command(name="revoke")
def auth_revoke(ctx: typer.Context) -> None:
    """Revoke Google OAuth tokens and delete local token storage."""
    state: CliState = ctx.obj

    config = load_config()
    tokens = load_tokens()

    if tokens:
        token_to_revoke = tokens.get("refresh_token") or tokens.get("access_token")
        if token_to_revoke and config:
            try:
                state.revoke_token(config, token_to_revoke)
            except (httpx.HTTPError, RuntimeError):
                print_cli_error(
                    state,
                    "revoke_failed",
                    "Google revocation failed. Tokens were kept for retry.",
                    exit_code=1,
                )

    try:
        delete_tokens()
    except RuntimeError:
        print_cli_error(
            state, "logout_failed", "Local credentials could not be cleared. Retry logout.", exit_code=1
        )

    if state.output_format == FormatEnum.JSON:
        if not state.quiet:
            emit_json({"revoked": True, "logged_out": True})
    elif not state.quiet:
        console.print(
            "[green]Success:[/green] Tokens revoked successfully and local tokens deleted.",
        )
