"""``core.camera.store`` — where saved camera positions live, and the JSON round trip.

Per ``docs/designs/camera-manager.md`` §8.1. Two families:

* :class:`TestAppDataDirectory` — the per-OS branch logic, exercised as the
  pure computation it is: ``platform.system`` monkeypatched, ``environ``
  injected, **no directory ever created**.
* :class:`TestCameraPositionStore` — the real thing against ``tmp_path``,
  because "the JSON round-trips" is not provable without actually writing a
  file and parsing it back.
"""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.camera.models import CameraOffset, SavedCameraPosition
from core.camera.store import (
    CameraPositionStore,
    CameraPositionStoreError,
    app_data_camera_positions_dir,
)

OFFSET = CameraOffset(
    forward_m=25.0, right_m=-10.0, up_m=8.0, look_offset_deg=45.0, pitch_deg=-12.0, zoom_ratio=1.5
)


@pytest.fixture
def store(tmp_path: Path) -> CameraPositionStore:
    """A store whose root does not exist yet — the state a first run is in."""
    return CameraPositionStore(tmp_path / "camera_positions")


class TestAppDataDirectory:
    """``app_data_camera_positions_dir`` — pure, no filesystem touched."""

    def test_windows_uses_appdata_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        appdata = "C:\\Users\\pilot\\AppData\\Roaming"
        root = app_data_camera_positions_dir(environ={"APPDATA": appdata})
        assert root == Path(appdata) / "OpenInstructorStation" / "camera_positions"

    def test_windows_falls_back_to_home_roaming(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        root = app_data_camera_positions_dir(environ={})
        assert (
            root
            == Path.home() / "AppData" / "Roaming" / "OpenInstructorStation" / "camera_positions"
        )

    def test_macos_uses_application_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        root = app_data_camera_positions_dir(environ={})
        assert root == (
            Path.home()
            / "Library"
            / "Application Support"
            / "OpenInstructorStation"
            / "camera_positions"
        )

    def test_linux_uses_xdg_data_home_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        root = app_data_camera_positions_dir(environ={"XDG_DATA_HOME": "/home/pilot/.data"})
        assert root == Path("/home/pilot/.data") / "OpenInstructorStation" / "camera_positions"

    def test_linux_falls_back_to_local_share(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        root = app_data_camera_positions_dir(environ={})
        assert (
            root == Path.home() / ".local" / "share" / "OpenInstructorStation" / "camera_positions"
        )

    def test_it_is_not_the_profiles_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two independent managers, two directories (D8/§10.1).

        The duplication of the app-data helper is deliberate and flagged; what
        would not be acceptable is the two stores quietly sharing one directory
        and reading each other's files.
        """
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        from core.profiles.paths import default_profiles_root

        assert app_data_camera_positions_dir(environ={}) != default_profiles_root(environ={})


class TestCameraPositionStore:
    """The save -> list -> get -> delete cycle, against a real directory."""

    def test_constructing_creates_nothing(self, tmp_path: Path) -> None:
        """Import-safe and construction-safe: nothing appears on disk until a write."""
        root = tmp_path / "camera_positions"
        CameraPositionStore(root)
        assert not root.exists()

    def test_listing_a_store_that_was_never_written_is_empty(
        self, store: CameraPositionStore
    ) -> None:
        assert store.list() == ()

    def test_save_then_list_then_get_then_delete(self, store: CameraPositionStore) -> None:
        saved = store.save("Base leg view", OFFSET)

        assert saved.name == "Base leg view"
        assert saved.offset == OFFSET
        assert saved.created_at.tzinfo is not None
        assert store.list() == (saved,)
        assert store.get(saved.position_id) == saved

        assert store.delete(saved.position_id) is True
        assert store.list() == ()
        assert store.get(saved.position_id) is None

    def test_deleting_twice_reports_the_second_as_already_gone(
        self, store: CameraPositionStore
    ) -> None:
        saved = store.save("Wing view", OFFSET)
        assert store.delete(saved.position_id) is True
        assert store.delete(saved.position_id) is False

    def test_each_save_gets_its_own_id(self, store: CameraPositionStore) -> None:
        first = store.save("One", OFFSET)
        second = store.save("One", OFFSET)

        assert first.position_id != second.position_id
        assert len(store.list()) == 2

    def test_the_stored_json_round_trips(self, store: CameraPositionStore) -> None:
        """What was written parses back as the same model — the point of §8.1.

        Reads the file directly rather than through the store, so a store that
        happened to cache in memory could not pass this.
        """
        saved = store.save("Three-quarter left", OFFSET)
        path = store.root / f"{saved.position_id}.json"

        assert SavedCameraPosition.model_validate_json(path.read_text(encoding="utf-8")) == saved

    def test_list_is_in_creation_order(self, store: CameraPositionStore) -> None:
        """Oldest first (§2), whatever order the directory listing happens to give.

        The timestamps are written by hand here rather than by three rapid
        ``save()`` calls on purpose: a coarse system clock can stamp two saves
        milliseconds apart identically, and a test that depended on that would
        be measuring the clock, not the store.
        """
        base = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
        for index, minutes in enumerate((30.0, 0.0, 15.0)):
            record = SavedCameraPosition(
                position_id=f"{index:032x}",
                name=f"Position {index}",
                offset=OFFSET,
                created_at=base + timedelta(minutes=minutes),
            )
            (store.root).mkdir(parents=True, exist_ok=True)
            (store.root / f"{record.position_id}.json").write_text(
                record.model_dump_json(), encoding="utf-8"
            )

        assert [saved.name for saved in store.list()] == [
            "Position 1",
            "Position 2",
            "Position 0",
        ]

    def test_an_unreadable_file_is_skipped_not_raised(self, store: CameraPositionStore) -> None:
        """A bad record never stops the browse — the navdata/profile-store rule."""
        good = store.save("Good", OFFSET)
        (store.root / "0123456789abcdef0123456789abcdef.json").write_text(
            "{not json", encoding="utf-8"
        )

        assert store.list() == (good,)

    def test_getting_a_corrupt_file_is_an_error_not_a_miss(
        self, store: CameraPositionStore
    ) -> None:
        """ "Not found" and "found but broken" are different answers (D8 storage posture)."""
        saved = store.save("Broken", OFFSET)
        (store.root / f"{saved.position_id}.json").write_text(
            json.dumps({"name": "Broken"}), encoding="utf-8"
        )

        with pytest.raises(CameraPositionStoreError):
            store.get(saved.position_id)

    @pytest.mark.parametrize(
        "position_id",
        ["", "../../../etc/passwd", "not-a-uuid", "0123456789ABCDEF0123456789ABCDEF"],
    )
    def test_an_id_this_store_could_never_have_assigned_is_a_miss(
        self, store: CameraPositionStore, position_id: str
    ) -> None:
        """An id off the wire never reaches the filesystem.

        ``Path`` joining does not collapse ``..``, so an id shaped like a path
        traversal would otherwise be handed straight to ``unlink()``.
        """
        assert store.get(position_id) is None
        assert store.delete(position_id) is False

    def test_a_traversal_id_cannot_delete_a_neighbouring_file(
        self, store: CameraPositionStore, tmp_path: Path
    ) -> None:
        """The shape check, proved rather than asserted."""
        victim = tmp_path / "victim.json"
        victim.write_text("{}", encoding="utf-8")

        assert store.delete("../victim") is False
        assert victim.exists()
