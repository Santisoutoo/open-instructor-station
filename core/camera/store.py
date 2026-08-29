"""Saved camera positions on disk — one flat directory of JSON files (D8).

Per ``docs/designs/camera-manager.md`` §6/§10.1. Reading and writing the
user's own application-data directory is not simulator I/O and does not
breach hard rule 2, the same reasoning ``core/navdata/`` and
``core/profiles/`` already rely on.

**Deliberately an independent module, not an import of**
``core.profiles.store``. The design (D8, §10.1) chose a flagged ~15-line
duplication of the app-data helper over a cross-manager dependency, because
"adding a manager must not require touching another one"
(``docs/architecture.md``). Training Profiles has since landed, so §10.1's own
resolution now applies: a follow-up ``chore/`` may factor
:func:`app_data_camera_positions_dir` and
``core.profiles.paths.default_profiles_root`` into a shared ``core/appdata.py``.
That is a separate, reviewable change — not something to do speculatively
inside a feature branch.

Import-safe: the constructor performs no I/O and creates no directory. Every
write ensures the directory exists immediately before writing and publishes
atomically (temp file in the same directory, then ``Path.replace``), the same
idiom the profile store and the navdata index build use. Every read treats a
missing directory as an empty store.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from core.camera.models import CameraOffset, SavedCameraPosition

__all__ = [
    "APP_NAME",
    "CameraPositionStore",
    "CameraPositionStoreError",
    "app_data_camera_positions_dir",
]

logger = logging.getLogger(__name__)

APP_NAME = "OpenInstructorStation"

#: :meth:`CameraPositionStore.save` only ever assigns ``uuid.uuid4().hex`` — 32
#: lowercase hex characters, no dashes. ``get``/``delete`` receive their id from
#: a URL, so it is untrusted: ``Path`` joining with ``/`` does not collapse
#: ``..`` segments, and an id shaped like ``../../../etc/passwd`` would
#: otherwise be handed straight to the filesystem. Anything not shaped like an
#: id this store could have assigned is answered as "not found" before a path is
#: ever built from it — ``core.profiles.store``'s own posture.
_VALID_POSITION_ID = re.compile(r"^[0-9a-f]{32}$")


class CameraPositionStoreError(RuntimeError):
    """The store itself failed — disk full, permission denied, unreadable content.

    Never raised for "not found": :meth:`CameraPositionStore.get` and
    :meth:`CameraPositionStore.delete` answer ``None``/``False`` instead.
    """


def app_data_camera_positions_dir(*, environ: Mapping[str, str] | None = None) -> Path:
    """The per-OS user application-data directory for saved camera positions.

    Pure computation, no I/O — building the path never creates it.

    * Windows: ``%APPDATA%/OpenInstructorStation/camera_positions``
    * macOS: ``~/Library/Application Support/OpenInstructorStation/camera_positions``
    * Linux/other POSIX (XDG Base Directory spec):
      ``$XDG_DATA_HOME/OpenInstructorStation/camera_positions``, falling back to
      ``~/.local/share/OpenInstructorStation/camera_positions``

    ``environ`` is injectable so a test never has to monkeypatch the process
    environment — the convention ``core.navdata.xplane_native.build.cache_directory``
    established. ``platform.system()`` rather than ``sys.platform`` for the same
    reason that module gives.
    """
    env = environ if environ is not None else os.environ

    system = platform.system()
    if system == "Windows":
        base = env.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / APP_NAME / "camera_positions"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "camera_positions"

    xdg = env.get("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / APP_NAME / "camera_positions"


class CameraPositionStore:
    """One flat directory of ``<position_id>.json`` files. No SQLite, no index.

    ``core.profiles.store``'s D5 reasoning transplanted: these records are
    user-authored, few and small, and a directory listing is the whole query
    surface.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        """Where this store reads and writes. Not guaranteed to exist yet."""
        return self._root

    def _path(self, position_id: str) -> Path:
        return self._root / f"{position_id}.json"

    def list(self) -> tuple[SavedCameraPosition, ...]:
        """Every saved position, in creation order.

        A file that will not parse is skipped and logged, never raised — the
        "a bad record never stops the browse" rule the profile store and the
        navdata index build already follow.

        Ordering is ``(created_at, position_id)``. The id tiebreak is not
        theoretical: the Windows system clock is coarse enough that two saves a
        few milliseconds apart can carry the *same* timestamp, and a sort on
        ``created_at`` alone would then order them arbitrarily from one call to
        the next. The tiebreak makes the order stable; it does not claim to
        recover which of two same-instant saves came first.
        """
        if not self._root.is_dir():
            return ()
        positions: list[SavedCameraPosition] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                positions.append(
                    SavedCameraPosition.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValidationError) as exc:
                logger.warning("Skipping unreadable saved camera position %s: %s", path, exc)
                continue
        positions.sort(key=lambda saved: (saved.created_at, saved.position_id))
        return tuple(positions)

    def save(self, name: str, offset: CameraOffset) -> SavedCameraPosition:
        """Assign an id and a UTC timestamp, write atomically, return the stored record.

        ``name`` is stored as given: the 1-60 character bound belongs to
        :class:`~core.camera.models.SaveCameraPositionRequest`, so a bad name is
        a 422 at the edge of the server rather than an exception from the
        bottom of the storage layer.
        """
        saved = SavedCameraPosition(
            position_id=uuid.uuid4().hex,
            name=name,
            offset=offset,
            created_at=datetime.now(UTC),
        )
        self._write(saved)
        return saved

    def get(self, position_id: str) -> SavedCameraPosition | None:
        """One saved position, or ``None`` when no file for ``position_id`` exists.

        Raises :class:`CameraPositionStoreError` when the file exists but will
        not parse — distinct from "not found", which is not an error.
        """
        if _VALID_POSITION_ID.match(position_id) is None:
            return None
        path = self._path(position_id)
        if not path.is_file():
            return None
        try:
            return SavedCameraPosition.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CameraPositionStoreError(
                f"Could not read camera position {position_id!r}: {exc}"
            ) from exc
        except ValidationError as exc:
            raise CameraPositionStoreError(
                f"Stored camera position {position_id!r} does not parse: {exc}"
            ) from exc

    def delete(self, position_id: str) -> bool:
        """``False`` when the file was already gone. Never raises for that case."""
        if _VALID_POSITION_ID.match(position_id) is None:
            return False
        try:
            self._path(position_id).unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CameraPositionStoreError(
                f"Could not delete camera position {position_id!r}: {exc}"
            ) from exc
        return True

    def _write(self, saved: SavedCameraPosition) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            tmp_path = self._root / f".{saved.position_id}.tmp"
            tmp_path.write_text(saved.model_dump_json(), encoding="utf-8")
            tmp_path.replace(self._path(saved.position_id))
        except OSError as exc:
            raise CameraPositionStoreError(
                f"Could not save camera position {saved.position_id!r}: {exc}"
            ) from exc
