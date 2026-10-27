import pytest

import ghealth.auth.token_store
import ghealth.config


@pytest.fixture(autouse=True)
def mock_config_dir(tmp_path, monkeypatch) -> None:
    """Sandboxes config paths for unit testing by redirecting to a temporary directory."""
    monkeypatch.setattr(ghealth.config, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(ghealth.auth.token_store, "get_config_dir", lambda: tmp_path)


@pytest.fixture(autouse=True)
def mock_keyring(monkeypatch):
    """Mock keyring password storage in memory."""
    store = {}

    def set_password(service, username, password) -> None:
        store[(service, username)] = password

    def get_password(service, username):
        return store.get((service, username))

    def delete_password(service, username) -> None:
        if (service, username) in store:
            del store[(service, username)]
        else:
            msg = "Password not found"
            raise Exception(msg)

    monkeypatch.setattr(ghealth.auth.token_store.keyring, "set_password", set_password)
    monkeypatch.setattr(ghealth.auth.token_store.keyring, "get_password", get_password)
    monkeypatch.setattr(ghealth.auth.token_store.keyring, "delete_password", delete_password)
    return store
