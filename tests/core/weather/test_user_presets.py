"""``WeatherPresetStore`` — the flat-JSON-directory storage layer, exercised end to end.

``tmp_path``-backed throughout, following ``tests/core/profiles/test_store.py``'s
discipline: nothing here mutates a committed fixture because there is no
committed fixture — every preset in this suite is built in-memory.
"""

from __future__ import annotations

import logging
import platform
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import core.weather.user_presets as user_presets_module
from core.weather.models import WeatherSetup
from core.weather.user_presets import (
    SavedWeatherPresetCreate,
    WeatherPresetStore,
    WeatherPresetStoreError,
    default_weather_presets_root,
)


def _setup() -> WeatherSetup:
    # Deliberately sparse: wind_layers=[] is an explicit "calm" command,
    # cloud_layers is left at its default None (untouched) — D3 semantics.
    return WeatherSetup(visibility_m=550.0, qnh_hpa=996.0, wind_layers=[])


def _draft(name: str = "Low vis drill") -> SavedWeatherPresetCreate:
    return SavedWeatherPresetCreate(name=name, description="A test preset.", setup=_setup())


@pytest.fixture
def store(tmp_path: Path) -> WeatherPresetStore:
    return WeatherPresetStore(tmp_path / "weather_presets")


class TestCreateGetRoundTrip:
    def test_create_then_get_round_trips_exactly(self, store: WeatherPresetStore) -> None:
        created = store.create(_draft())
        fetched = store.get(created.preset_id)
        assert fetched == created

    def test_create_assigns_a_32_char_uuid4_hex_id(self, store: WeatherPresetStore) -> None:
        created = store.create(_draft())
        assert len(created.preset_id) == 32
        int(created.preset_id, 16)  # raises if not hex

    def test_create_sets_created_and_updated_to_the_same_instant(
        self, store: WeatherPresetStore
    ) -> None:
        created = store.create(_draft())
        assert created.created_at == created.updated_at

    def test_get_on_unknown_id_returns_none(self, store: WeatherPresetStore) -> None:
        assert store.get("0" * 32) is None

    def test_directory_is_not_created_until_the_first_write(
        self, tmp_path: Path, store: WeatherPresetStore
    ) -> None:
        root = tmp_path / "weather_presets"
        assert not root.exists()
        store.create(_draft())
        assert root.is_dir()

    def test_write_publishes_atomically_leaving_no_temp_file(
        self, tmp_path: Path, store: WeatherPresetStore
    ) -> None:
        created = store.create(_draft())
        root = tmp_path / "weather_presets"
        entries = sorted(p.name for p in root.iterdir())
        assert entries == [f"{created.preset_id}.json"]

    def test_sparse_setup_none_vs_empty_list_survives_the_round_trip(
        self, store: WeatherPresetStore
    ) -> None:
        created = store.create(_draft())
        fetched = store.get(created.preset_id)
        assert fetched is not None
        assert fetched.setup.cloud_layers is None
        assert fetched.setup.wind_layers == []

    def test_duplicate_names_coexist_as_distinct_presets(self, store: WeatherPresetStore) -> None:
        first = store.create(_draft("Same"))
        second = store.create(_draft("Same"))
        assert first.preset_id != second.preset_id
        ids = {preset.preset_id for preset in store.list()}
        assert {first.preset_id, second.preset_id} <= ids


class TestUntrustedPresetId:
    """`preset_id` reaches `get`/`delete` straight from a URL path parameter, so it
    is untrusted input — a shape not matching what `create()` ever assigns must
    never reach a filesystem path (the same defense-in-depth `core.profiles.store`
    and `core.camera.store` already apply)."""

    def test_get_on_a_traversal_shaped_id_returns_none(
        self, tmp_path: Path, store: WeatherPresetStore
    ) -> None:
        # A real file placed just outside the store's own root -- if the guard were
        # missing, `../secret` would resolve to exactly this file.
        secret = tmp_path / "secret.json"
        secret.write_text("not a preset", encoding="utf-8")
        assert store.get("../secret") is None

    def test_delete_on_a_traversal_shaped_id_returns_false_and_does_not_touch_the_file(
        self, tmp_path: Path, store: WeatherPresetStore
    ) -> None:
        secret = tmp_path / "secret.json"
        secret.write_text("not a preset", encoding="utf-8")
        assert store.delete("../secret") is False
        assert secret.exists()

    def test_get_on_an_id_of_the_wrong_length_returns_none(self, store: WeatherPresetStore) -> None:
        assert store.get("a" * 31) is None
        assert store.get("a" * 33) is None

    def test_get_on_a_non_hex_id_returns_none(self, store: WeatherPresetStore) -> None:
        assert store.get("g" * 32) is None


class TestList:
    def test_empty_store_lists_nothing(self, store: WeatherPresetStore) -> None:
        assert store.list() == []

    def test_missing_directory_is_an_empty_store(self, tmp_path: Path) -> None:
        store = WeatherPresetStore(tmp_path / "does-not-exist")
        assert store.list() == []

    def test_lists_newest_created_at_first(
        self, store: WeatherPresetStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two back-to-back ``store.create()`` calls need distinguishable
        ``created_at`` instants for "newest first" to have a defined answer --
        some CI runners (observed: GitHub Actions windows-latest) have wall-clock
        resolution coarse enough that consecutive ``datetime.now(UTC)`` calls tie,
        which made the equivalent profile-store test flaky rather than wrong.
        Controlling the clock removes the platform dependency without weakening
        what's actually being verified.
        """
        instants = iter(
            [datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC), datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)]
        )
        monkeypatch.setattr(
            user_presets_module,
            "datetime",
            type("_FixedClock", (), {"now": staticmethod(lambda tz=None: next(instants))}),
        )

        first = store.create(_draft("First"))
        second = store.create(_draft("Second"))
        presets = store.list()
        assert [preset.preset_id for preset in presets] == [second.preset_id, first.preset_id]

    def test_skips_a_corrupt_file_without_raising_and_logs_it(
        self, tmp_path: Path, store: WeatherPresetStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        good = store.create(_draft("Good"))
        root = tmp_path / "weather_presets"
        (root / "corrupt.json").write_text("{not valid json", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            presets = store.list()

        assert [preset.preset_id for preset in presets] == [good.preset_id]
        assert any(
            "Skipping unreadable saved weather preset" in record.message
            for record in caplog.records
        )


class TestDelete:
    def test_delete_on_unknown_id_returns_false(self, store: WeatherPresetStore) -> None:
        assert store.delete("0" * 32) is False

    def test_delete_removes_the_preset(self, store: WeatherPresetStore) -> None:
        created = store.create(_draft())
        assert store.delete(created.preset_id) is True
        assert store.get(created.preset_id) is None

    def test_delete_twice_the_second_time_returns_false(self, store: WeatherPresetStore) -> None:
        created = store.create(_draft())
        store.delete(created.preset_id)
        assert store.delete(created.preset_id) is False


class TestWeatherPresetStoreError:
    def test_get_on_unparseable_content_raises_store_error_not_not_found(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "weather_presets"
        root.mkdir()
        preset_id = "a" * 32
        (root / f"{preset_id}.json").write_text("{not valid json", encoding="utf-8")
        store = WeatherPresetStore(root)
        with pytest.raises(WeatherPresetStoreError):
            store.get(preset_id)


class TestSavedWeatherPresetCreate:
    def test_extra_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SavedWeatherPresetCreate.model_validate({"name": "X", "setup": {}, "colour": "blue"})

    def test_nameless_body_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SavedWeatherPresetCreate.model_validate({"setup": {}})


class TestDefaultWeatherPresetsRoot:
    """Mirrors ``tests/core/profiles/test_paths.py``'s pattern: ``platform.system``
    is monkeypatched (the module under test calls it), ``environ`` is passed
    explicitly per case rather than touching the real process environment."""

    def test_windows_uses_appdata_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        appdata = "C:\\Users\\pilot\\AppData\\Roaming"
        root = default_weather_presets_root(environ={"APPDATA": appdata})
        assert root == Path(appdata) / "OpenInstructorStation" / "weather_presets"

    def test_windows_falls_back_to_home_appdata_roaming_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        root = default_weather_presets_root(environ={})
        assert root == (
            Path.home() / "AppData" / "Roaming" / "OpenInstructorStation" / "weather_presets"
        )

    def test_macos_uses_application_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        root = default_weather_presets_root(environ={})
        assert root == (
            Path.home()
            / "Library"
            / "Application Support"
            / "OpenInstructorStation"
            / "weather_presets"
        )

    def test_linux_uses_xdg_data_home_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        root = default_weather_presets_root(environ={"XDG_DATA_HOME": "/home/pilot/.data"})
        assert root == Path("/home/pilot/.data") / "OpenInstructorStation" / "weather_presets"

    def test_linux_falls_back_to_local_share_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        root = default_weather_presets_root(environ={})
        assert root == (
            Path.home() / ".local" / "share" / "OpenInstructorStation" / "weather_presets"
        )

    def test_calling_it_creates_nothing_on_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        root = default_weather_presets_root(environ={"XDG_DATA_HOME": str(tmp_path)})
        assert not root.exists()
