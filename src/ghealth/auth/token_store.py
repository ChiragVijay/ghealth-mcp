import contextlib
import json
from pathlib import Path

import keyring
from keyring.errors import KeyringError, NoKeyringError

from ghealth.config import get_config_dir, load_config
from ghealth.local_files import write_private_file


def get_token_path() -> Path:
    """Return the path to tokens.json when using file-based storage."""
    return get_config_dir() / "tokens.json"


def _load_from_file() -> dict | None:
    """Load tokens from the local file."""
    path = get_token_path()
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _load_from_keyring() -> dict | None:
    """Load tokens from the OS keyring."""
    try:
        val = keyring.get_password("ghealth", "tokens")
        if val:
            value = json.loads(val)
            return value if isinstance(value, dict) else None
    except (json.JSONDecodeError, KeyringError):
        return None
    return None


def _save_to_file(tokens: dict) -> None:
    """Save tokens to a local file with restricted permissions (owner read/write only)."""
    write_private_file(get_token_path(), json.dumps(tokens, indent=2))


def _save_to_keyring(tokens: dict) -> None:
    """Save tokens to the OS keyring. Raises KeyringError on failure."""
    keyring.set_password("ghealth", "tokens", json.dumps(tokens))


def load_tokens() -> dict | None:
    """
    Load OAuth tokens.

    Uses the configured storage backend:
    - ``auto``: read the authoritative local file, fall back to keyring for legacy stores.
    - ``keyring``: keyring only.
    - ``plaintext``: local file only.
    """
    config = load_config()
    storage = "auto" if not config else config.token_storage

    if storage == "plaintext":
        return _load_from_file()

    if storage == "auto":
        # The file is saved first and remains current even if a keyring update fails.
        if get_token_path().exists():
            return _load_from_file()
        return _load_from_keyring()

    # storage == "keyring"
    return _load_from_keyring()


def save_tokens(tokens: dict) -> None:
    """
    Save OAuth tokens.

    Uses the configured storage backend:
    - ``auto``: write to local file (0600 perms) AND keyring (best-effort).
    - ``keyring``: keyring only; raises RuntimeError on failure.
    - ``plaintext``: local file only (0600 perms).
    """
    config = load_config()
    storage = "auto" if not config else config.token_storage

    if storage == "plaintext":
        _save_to_file(tokens)
        return

    if storage == "auto":
        _save_to_file(tokens)
        with contextlib.suppress(KeyringError):
            _save_to_keyring(tokens)
        return

    get_config_dir().mkdir(parents=True, exist_ok=True)
    try:
        _save_to_keyring(tokens)
    except KeyringError as e:
        msg = (
            f"Failed to store tokens in OS keyring: {e}.\n"
            "Consider switching to 'auto' storage for automatic fallback:\n"
            "ghealth auth configure --token-storage auto"
        )
        raise RuntimeError(msg) from e


def delete_tokens() -> None:
    """Delete all local token information from both plaintext files and the OS keyring."""
    failed = []
    try:
        get_token_path().unlink(missing_ok=True)
    except OSError:
        failed.append("local token file")
    try:
        if keyring.get_password("ghealth", "tokens") is not None:
            keyring.delete_password("ghealth", "tokens")
    except NoKeyringError:
        config = load_config()
        if config and config.token_storage == "keyring":
            failed.append("OS keyring (backend unavailable)")
    except (KeyringError, OSError):
        failed.append("OS keyring")
    if failed:
        raise RuntimeError(f"Could not clear {', '.join(failed)}. Unlock the store and retry logout.")
