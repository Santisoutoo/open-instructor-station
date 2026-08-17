"""``default_profiles_root`` — the per-OS branch logic, exercised directly.

Pure function, no filesystem touched: every case only asserts the computed
``Path``, never creates it. ``platform.system`` is monkeypatched rather than
``sys.platform`` (the module under test calls the former), and ``environ`` is
passed explicitly per case rather than touching the real process environment
— the exact injectable-``environ`` convention
``core.navdata.xplane_native.build.cache_directory`` established.
"""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from core.profiles import paths


class TestWindows:
    def test_uses_appdata_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        appdata = "C:\\Users\\pilot\\AppData\\Roaming"
        root = paths.default_profiles_root(environ={"APPDATA": appdata})
        assert root == Path(appdata) / "OpenInstructorStation" / "profiles"

    def test_falls_back_to_home_appdata_roaming_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        root = paths.default_profiles_root(environ={})
        assert root == Path.home() / "AppData" / "Roaming" / "OpenInstructorStation" / "profiles"


class TestMacOS:
    def test_uses_application_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        root = paths.default_profiles_root(environ={})
        assert root == (
            Path.home() / "Library" / "Application Support" / "OpenInstructorStation" / "profiles"
        )


class TestLinux:
    def test_uses_xdg_data_home_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        root = paths.default_profiles_root(environ={"XDG_DATA_HOME": "/home/pilot/.data"})
        assert root == Path("/home/pilot/.data") / "OpenInstructorStation" / "profiles"

    def test_falls_back_to_local_share_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        root = paths.default_profiles_root(environ={})
        assert root == Path.home() / ".local" / "share" / "OpenInstructorStation" / "profiles"
