import base64
import hashlib
import queue
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from ghealth.config import Config

HTTP_OK = 200


class OAuthRedirectServer(HTTPServer):
    expected_state: str | None = None
    code_queue: queue.Queue[tuple[str | None, str | None]]

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2.0)
        return connection, address


class RedirectHandler(BaseHTTPRequestHandler):
    server: OAuthRedirectServer

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        expected = self.server.expected_state
        if expected and (not state or not secrets.compare_digest(expected, state)):
            self.send_error(400, "OAuth state mismatch")
            return
        if not code and "error" not in params:
            self.send_error(400, "Missing OAuth response")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.end_headers()
        message = (
            "Google authorization received. Return to the terminal to finish setup."
            if code
            else "Google authorization declined. Return to the terminal to retry."
        )
        self.wfile.write(f"<!doctype html><html><title>G Health MCP</title><p>{message}</p></html>".encode())
        self.server.code_queue.put((code, state))


def generate_pkce() -> tuple[str, str]:
    """Generate a code verifier and code challenge for PKCE."""
    code_verifier = secrets.token_urlsafe(64)
    hashed = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(hashed).decode("utf-8").replace("=", "")
    return code_verifier, code_challenge


def run_local_redirect_server() -> tuple[OAuthRedirectServer, int]:
    """Start a local HTTP server on an ephemeral port to listen for the redirect callback."""
    server = OAuthRedirectServer(("127.0.0.1", 0), RedirectHandler)
    server.code_queue = queue.Queue()
    server.timeout = 1.0
    return server, server.server_address[1]


def extract_code_from_input(user_input: str) -> str:
    """Extract authorization code from either the raw pasted code or redirect URL."""
    user_input = user_input.strip()
    if user_input.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(user_input)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            return code
    return user_input


def exchange_code_for_tokens(
    config: Config,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict:
    """Exchanges an OAuth authorization code for access and refresh tokens."""
    payload = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    resp = httpx.post(config.token_uri, data=payload)
    if resp.status_code != HTTP_OK:
        try:
            err_data = resp.json()
            err_msg = err_data.get("error_description") or err_data.get("error") or resp.text
        except ValueError:
            err_msg = resp.text
        msg = f"Token exchange failed: {err_msg}"
        raise RuntimeError(msg)

    data = resp.json()
    if "expires_in" in data:
        data["expires_at"] = int(time.time()) + data["expires_in"]
    return data


def refresh_access_token(config: Config, refresh_token: str) -> dict:
    """Refresh the access token using the stored refresh token."""
    payload = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    resp = httpx.post(config.token_uri, data=payload)
    if resp.status_code != HTTP_OK:
        try:
            err_data = resp.json()
            err_msg = err_data.get("error_description") or err_data.get("error") or resp.text
        except ValueError:
            err_msg = resp.text
        msg = f"Token refresh failed: {err_msg}"
        raise RuntimeError(msg)

    data = resp.json()
    if "expires_in" in data:
        data["expires_at"] = int(time.time()) + data["expires_in"]
    if "refresh_token" not in data:
        data["refresh_token"] = refresh_token
    return data


def revoke_token(config: Config, token: str) -> None:
    """Revokes the given token (refresh or access token) on Google's servers."""
    _ = config
    response = httpx.post(
        "https://oauth2.googleapis.com/revoke",
        data={"token": token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code == 400:
        try:
            error = response.json()
        except ValueError:
            error = {}
        if isinstance(error, dict) and error.get("error") == "invalid_token":
            return  # Already invalid; local credentials can safely be removed.
    response.raise_for_status()
