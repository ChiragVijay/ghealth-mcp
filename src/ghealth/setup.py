"""One-time Google desktop OAuth setup, independent of any MCP host."""

import secrets
import time
import urllib.parse
import webbrowser
from collections.abc import Callable
from pathlib import Path

from ghealth.auth.oauth import exchange_code_for_tokens, generate_pkce, run_local_redirect_server
from ghealth.auth.scopes import get_scopes_for_login
from ghealth.auth.token_store import delete_tokens, save_tokens
from ghealth.config import Config, load_config, parse_credentials_json, save_config


def configure_desktop(credentials: Path) -> Config:
    """Import a Desktop app client. Keep the existing token store on upgrades."""
    import json

    document = json.loads(credentials.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not document.get("installed"):
        raise ValueError("Download a Desktop app OAuth client JSON, rather than a Web application client.")
    values = parse_credentials_json(credentials)
    # Only Google's official endpoints are used for new desktop setups.
    config = Config(client_id=values["client_id"], client_secret=values["client_secret"])
    existing = load_config()
    if existing:
        config.token_storage = existing.token_storage
        if existing.client_id != config.client_id or existing.client_secret != config.client_secret:
            delete_tokens()
    save_config(config)
    return config


def login_desktop(
    config: Config,
    *,
    scope_profile: str = "readonly",
    extra_scopes: str | None = None,
    show_url: Callable[[str], None],
    timeout: float = 600,
) -> None:
    """Authorize with PKCE and a loopback callback, then persist refresh credentials."""
    scopes = get_scopes_for_login(scope_profile, extra_scopes)
    verifier, challenge = generate_pkce()
    expected_state = secrets.token_urlsafe(32)
    server, port = run_local_redirect_server()
    server.expected_state = expected_state
    redirect_uri = f"http://127.0.0.1:{port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": expected_state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    try:
        show_url(url)
        webbrowser.open(url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            server.handle_request()
            if server.code_queue.empty():
                continue
            code, returned_state = server.code_queue.get_nowait()
            if not returned_state or not secrets.compare_digest(returned_state, expected_state):
                raise RuntimeError("OAuth state mismatch. Run setup again.")
            if not code:
                raise RuntimeError("Google authorization was declined. Run setup again to authorize.")
            tokens = exchange_code_for_tokens(config, code, verifier, redirect_uri)
            if not tokens.get("access_token") or not tokens.get("refresh_token"):
                raise RuntimeError(
                    "Google did not return offline credentials. Run setup again and grant access."
                )
            tokens.setdefault("scope", " ".join(scopes))
            save_tokens(tokens)
            return
        raise RuntimeError(
            "Google sign-in timed out. Run ghealth-mcp setup again and finish browser consent."
        )
    finally:
        server.server_close()
