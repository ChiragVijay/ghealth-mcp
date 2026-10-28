from types import SimpleNamespace

import pytest

import ghealth.config as config
from ghealth.config import get_config_dir as resolve_config_dir


def test_windows_agents_reuse_setup_directory_despite_known_folder_redirection(tmp_path, monkeypatch):
    local_app_data = tmp_path / "user-profile" / "AppData" / "Local"
    redirected = tmp_path / "sandbox" / "AC" / "ghealth" / "ghealth"
    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(config, "user_config_dir", lambda **kwargs: str(redirected))

    assert resolve_config_dir() == local_app_data / "ghealth" / "ghealth"


@pytest.mark.parametrize("local_app_data", [None, "", "relative-profile"])
def test_windows_missing_or_relative_profile_uses_platform_directory(tmp_path, monkeypatch, local_app_data):
    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="win32"))
    if local_app_data is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    else:
        monkeypatch.setenv("LOCALAPPDATA", local_app_data)
    monkeypatch.setattr(config, "user_config_dir", lambda **kwargs: str(tmp_path))

    assert resolve_config_dir() == tmp_path


def test_other_platforms_keep_platform_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "unrelated"))
    monkeypatch.setattr(config, "user_config_dir", lambda **kwargs: str(tmp_path))

    assert resolve_config_dir() == tmp_path
