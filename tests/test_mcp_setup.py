import json
import queue
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from ghealth.auth.oauth import run_local_redirect_server
from ghealth.config import Config, load_config
from ghealth.setup import configure_desktop, login_desktop


def test_import_desktop_and_reject_web(tmp_path) -> None:
    path = tmp_path / "desktop.json"
    path.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "secret"}}))
    assert configure_desktop(path).client_id == "id"
    config = load_config()
    assert config is not None and config.client_id == "id"
    path.write_text(json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}))
    with pytest.raises(ValueError, match="Desktop"):
        configure_desktop(path)


@pytest.mark.parametrize("outcome", ["success", "denied", "state", "timeout", "missing_refresh"])
def test_login_pkce_and_callback(monkeypatch, outcome) -> None:
    class FakeServer:
        code_queue = queue.Queue()
        expected_state = None
        closed = False

        def handle_request(self):
            pass

        def server_close(self):
            self.closed = True

    server = FakeServer()
    saved = []
    monkeypatch.setattr("ghealth.setup.run_local_redirect_server", lambda: (server, 12345))
    monkeypatch.setattr("ghealth.setup.save_tokens", saved.append)

    def open_browser(url):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert params["redirect_uri"] == ["http://127.0.0.1:12345"]
        assert params["access_type"] == ["offline"]
        assert params["code_challenge_method"] == ["S256"]
        assert all("writeonly" not in scope for scope in params["scope"][0].split())
        code = None if outcome == "denied" else "test-code"
        state = "wrong" if outcome == "state" else params["state"][0]
        if outcome != "timeout":
            server.code_queue.put((code, state))
        return True

    def exchange(config, code, verifier, redirect):
        import base64
        import hashlib

        assert code == "test-code"
        params = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        assert params["code_challenge"] == [challenge]
        tokens = {"access_token": "test-access"}
        if outcome != "missing_refresh":
            tokens["refresh_token"] = "test-refresh"
        return tokens

    monkeypatch.setattr("ghealth.setup.webbrowser.open", open_browser)
    monkeypatch.setattr("ghealth.setup.exchange_code_for_tokens", exchange)
    urls = []
    config = Config(client_id="id", client_secret="secret")
    if outcome == "success":
        login_desktop(config, show_url=urls.append)
        assert saved[0]["refresh_token"] == "test-refresh"
    else:
        with pytest.raises(RuntimeError):
            login_desktop(config, show_url=urls.append, timeout=0 if outcome == "timeout" else 1)
        assert not saved
    assert server.closed


def test_loopback_rejects_wrong_state_and_accepts_callback() -> None:
    server, port = run_local_redirect_server()
    server.expected_state = "expected"
    try:
        with ThreadPoolExecutor(max_workers=1) as executor, httpx.Client(trust_env=False) as client:
            pending = executor.submit(server.handle_request)
            bad = client.get(f"http://127.0.0.1:{port}/?code=bad&state=wrong")
            pending.result(timeout=5)
            assert bad.status_code == 400
            assert server.code_queue.empty()
            pending = executor.submit(server.handle_request)
            good = client.get(f"http://127.0.0.1:{port}/?code=good&state=expected")
            pending.result(timeout=5)
            assert good.status_code == 200
            assert server.code_queue.get_nowait() == ("good", "expected")
            assert "fonts.googleapis.com" not in good.text
    finally:
        server.server_close()
