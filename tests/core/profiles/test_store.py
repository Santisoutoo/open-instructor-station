"""``ProfileStore`` — the flat-JSON-directory storage layer, exercised end to end.

``tmp_path``-backed throughout, following ``tests/core/navdata/test_index_build.py``'s
discipline: nothing here mutates a committed fixture because there is no
committed fixture — every profile in this suite is built in-memory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import core.profiles.store as profile_store_module
from core.profiles.models import TrainingProfile, TrainingProfileCreate
from core.profiles.store import ProfileStore, ProfileStoreError
from core.scenarios.models import ScenarioDocument
from core.weather.models import WeatherRequest


def _scenario() -> ScenarioDocument:
    return ScenarioDocument(
        name="Test scenario",
        description="A minimal scenario embedded in a profile for storage tests.",
        weather=WeatherRequest(preset="cavok"),
    )


def _draft(name: str = "Circuit practice") -> TrainingProfileCreate:
    return TrainingProfileCreate(
        name=name, description="A test profile.", author="Instructor", scenario=_scenario()
    )


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles")


class TestCreateGetRoundTrip:
    def test_create_then_get_round_trips_exactly(self, store: ProfileStore) -> None:
        created = store.create(_draft())
        fetched = store.get(created.profile_id)
        assert fetched == created

    def test_create_assigns_a_32_char_uuid4_hex_id(self, store: ProfileStore) -> None:
        created = store.create(_draft())
        assert len(created.profile_id) == 32
        int(created.profile_id, 16)  # raises if not hex

    def test_create_sets_created_and_updated_to_the_same_instant(self, store: ProfileStore) -> None:
        created = store.create(_draft())
        assert created.created_at == created.updated_at

    def test_get_on_unknown_id_returns_none(self, store: ProfileStore) -> None:
        assert store.get("0" * 32) is None

    def test_directory_is_not_created_until_the_first_write(
        self, tmp_path: Path, store: ProfileStore
    ) -> None:
        root = tmp_path / "profiles"
        assert not root.exists()
        store.create(_draft())
        assert root.is_dir()


class TestUntrustedProfileId:
    """`profile_id` reaches `get`/`delete` straight from a URL path parameter, so it
    is untrusted input — a shape not matching what `create()` ever assigns must
    never reach a filesystem path (PR #108 review, defense-in-depth)."""

    def test_get_on_a_traversal_shaped_id_returns_none(
        self, tmp_path: Path, store: ProfileStore
    ) -> None:
        # A real file placed just outside the store's own root -- if the guard were
        # missing, `../secret` would resolve to exactly this file.
        secret = tmp_path / "secret.json"
        secret.write_text("not a profile", encoding="utf-8")
        assert store.get("../secret") is None

    def test_delete_on_a_traversal_shaped_id_returns_false_and_does_not_touch_the_file(
        self, tmp_path: Path, store: ProfileStore
    ) -> None:
        secret = tmp_path / "secret.json"
        secret.write_text("not a profile", encoding="utf-8")
        assert store.delete("../secret") is False
        assert secret.exists()

    def test_get_on_an_id_of_the_wrong_length_returns_none(self, store: ProfileStore) -> None:
        assert store.get("a" * 31) is None
        assert store.get("a" * 33) is None

    def test_get_on_a_non_hex_id_returns_none(self, store: ProfileStore) -> None:
        assert store.get("g" * 32) is None

    def test_export_on_a_traversal_shaped_id_returns_none(self, store: ProfileStore) -> None:
        assert store.export_bytes("../../etc/passwd") is None

    def test_replace_on_a_traversal_shaped_id_returns_none(self, store: ProfileStore) -> None:
        assert store.replace("../../etc/passwd", _draft()) is None


class TestList:
    def test_empty_store_lists_nothing(self, store: ProfileStore) -> None:
        assert store.list() == []

    def test_missing_directory_is_an_empty_store(self, tmp_path: Path) -> None:
        store = ProfileStore(tmp_path / "does-not-exist")
        assert store.list() == []

    def test_lists_newest_updated_at_first(
        self, store: ProfileStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two back-to-back ``store.create()`` calls need distinguishable
        ``updated_at`` instants for "newest first" to have a defined answer --
        some CI runners (observed: GitHub Actions windows-latest) have wall-clock
        resolution coarse enough that consecutive ``datetime.now(UTC)`` calls tie,
        which made this test flaky rather than wrong. Controlling the clock removes
        the platform dependency without weakening what's actually being verified.
        """
        instants = iter(
            [datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC), datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)]
        )
        monkeypatch.setattr(
            profile_store_module,
            "datetime",
            type("_FixedClock", (), {"now": staticmethod(lambda tz=None: next(instants))}),
        )

        first = store.create(_draft("First"))
        second = store.create(_draft("Second"))
        summaries = store.list()
        assert [summary.profile_id for summary in summaries] == [
            second.profile_id,
            first.profile_id,
        ]

    def test_skips_a_corrupt_file_without_raising(
        self, tmp_path: Path, store: ProfileStore
    ) -> None:
        good = store.create(_draft("Good"))
        root = tmp_path / "profiles"
        (root / "corrupt.json").write_text("{not valid json", encoding="utf-8")

        summaries = store.list()

        assert [summary.profile_id for summary in summaries] == [good.profile_id]

    def test_airport_icao_teaser_is_none_for_a_weather_only_profile(
        self, store: ProfileStore
    ) -> None:
        created = store.create(_draft())
        summary = next(s for s in store.list() if s.profile_id == created.profile_id)
        assert summary.airport_icao is None


class TestReplace:
    def test_replace_on_unknown_id_returns_none(self, store: ProfileStore) -> None:
        assert store.replace("0" * 32, _draft()) is None

    def test_replace_keeps_id_and_created_at_bumps_updated_at(self, store: ProfileStore) -> None:
        created = store.create(_draft("Original"))
        replaced = store.replace(created.profile_id, _draft("Renamed"))
        assert replaced is not None
        assert replaced.profile_id == created.profile_id
        assert replaced.created_at == created.created_at
        assert replaced.updated_at >= created.updated_at
        assert replaced.name == "Renamed"

    def test_replace_persists(self, store: ProfileStore) -> None:
        created = store.create(_draft("Original"))
        store.replace(created.profile_id, _draft("Renamed"))
        assert store.get(created.profile_id).name == "Renamed"  # type: ignore[union-attr]


class TestDelete:
    def test_delete_on_unknown_id_returns_false(self, store: ProfileStore) -> None:
        assert store.delete("0" * 32) is False

    def test_delete_removes_the_profile(self, store: ProfileStore) -> None:
        created = store.create(_draft())
        assert store.delete(created.profile_id) is True
        assert store.get(created.profile_id) is None

    def test_delete_twice_the_second_time_returns_false(self, store: ProfileStore) -> None:
        created = store.create(_draft())
        store.delete(created.profile_id)
        assert store.delete(created.profile_id) is False


class TestImportExport:
    def test_import_ignores_an_embedded_profile_id_and_assigns_a_fresh_one(
        self, store: ProfileStore
    ) -> None:
        original = store.create(_draft("Exported"))
        raw = store.export_bytes(original.profile_id)
        assert raw is not None

        imported = store.import_bytes(raw)

        assert imported.profile_id != original.profile_id
        assert imported.name == original.name
        assert imported.scenario == original.scenario

    def test_import_on_malformed_json_raises_validation_error(self, store: ProfileStore) -> None:
        with pytest.raises(ValidationError):
            store.import_bytes(b"{not valid json")

    def test_import_on_schema_violation_raises_validation_error(self, store: ProfileStore) -> None:
        with pytest.raises(ValidationError):
            store.import_bytes(b'{"description": "missing a name and a scenario"}')

    def test_export_on_unknown_id_returns_none(self, store: ProfileStore) -> None:
        assert store.export_bytes("0" * 32) is None

    def test_export_round_trips_through_model_validate_json(self, store: ProfileStore) -> None:
        created = store.create(_draft())
        raw = store.export_bytes(created.profile_id)
        assert raw is not None
        assert TrainingProfile.model_validate_json(raw) == created


class TestProfileStoreError:
    def test_get_on_unparseable_content_raises_store_error_not_not_found(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "profiles"
        root.mkdir()
        profile_id = "a" * 32
        (root / f"{profile_id}.json").write_text("{not valid json", encoding="utf-8")
        store = ProfileStore(root)
        with pytest.raises(ProfileStoreError):
            store.get(profile_id)
