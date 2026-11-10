"""User-saved weather presets on disk — one flat directory of JSON files (WS-4).

Reading and writing the user's own application-data directory is not
simulator I/O and does not breach hard rule 2, the same reasoning
``core/navdata/``, ``core/profiles/`` and ``core/camera/`` already rely on.

**Deliberately an independent module, not an import of** ``core.profiles.store``
or ``core.camera.store``. Same call ``core/camera/store.py`` already made
(D8, §10.1): a flagged ~15-line duplication of the app-data helper over a
cross-manager dependency, because "adding a manager must not require touching
another one" (``docs/architecture.md``). A follow-up ``chore/`` may factor
this alongside its siblings into a shared ``core/appdata.py`` — a separate,
reviewable change, not something to do speculatively inside a feature branch.

Import-safe: the constructor performs no I/O and creates no directory. Every
write ensures the directory exists immediately before writing and publishes
atomically (temp file in the same directory, then ``Path.replace``), the same
idiom the profile and camera stores use. Every read treats a missing
directory as an empty store.
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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.weather.models import WeatherSetup

__all__ = [
    "APP_NAME",
    "WEATHER_PRESET_FORMAT_VERSION",
    "SavedWeatherPreset",
    "SavedWeatherPresetCreate",
    "WeatherPresetStore",
    "WeatherPresetStoreError",
    "default_weather_presets_root",
]

logger = logging.getLogger(__name__)

APP_NAME = "OpenInstructorStation"
WEATHER_PRESET_FORMAT_VERSION = 1

#: :meth:`WeatherPresetStore.create` only ever assigns ``uuid.uuid4().hex`` — 32
#: lowercase hex characters, no dashes. ``get``/``delete`` receive their id from
#: a URL, so it is untrusted: ``Path`` joining with ``/`` does not collapse
#: ``..`` segments, and an id shaped like ``../../../etc/passwd`` would
#: otherwise be handed straight to the filesystem. Anything not shaped like an
#: id this store could have assigned is answered as "not found" before a path
#: is ever built from it — ``core.profiles.store``'s own posture.
_VALID_PRESET_ID = re.compile(r"^[0-9a-f]{32}$")


class WeatherPresetStoreError(RuntimeError):
    """The store itself failed — disk full, permission denied, unreadable content.

    Never raised for "not found": :meth:`WeatherPresetStore.get` and
    :meth:`WeatherPresetStore.delete` answer ``None``/``False`` instead.
    """


def default_weather_presets_root(*, environ: Mapping[str, str] | None = None) -> Path:
    """The per-OS user application-data directory for user-saved weather presets.

    Pure computation, no I/O — building the path never creates it.

    * Windows: ``%APPDATA%/OpenInstructorStation/weather_presets``
    * macOS: ``~/Library/Application Support/OpenInstructorStation/weather_presets``
    * Linux/other POSIX (XDG Base Directory spec):
      ``$XDG_DATA_HOME/OpenInstructorStation/weather_presets``, falling back to
      ``~/.local/share/OpenInstructorStation/weather_presets``

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
        return root / APP_NAME / "weather_presets"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "weather_presets"

    xdg = env.get("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / APP_NAME / "weather_presets"


class SavedWeatherPreset(BaseModel):
    """A user-saved weather preset as stored on disk.

    ``extra="ignore"`` (unlike :class:`SavedWeatherPresetCreate`'s
    ``extra="forbid"``, deliberately): this is the model an older app build
    reads back, so an unrecognised field from a newer ``format_version``
    is dropped rather than rejected — the same forward-compat posture
    ``core.profiles.models.TrainingProfile`` takes.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    format_version: int = Field(default=WEATHER_PRESET_FORMAT_VERSION)
    preset_id: str = Field(min_length=32, max_length=32)
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=2000)
    setup: WeatherSetup
    created_at: datetime
    updated_at: datetime


class SavedWeatherPresetCreate(BaseModel):
    """The request body for saving a new weather preset.

    ``extra="forbid"``: a hand-edited body that misspells a field should fail
    loudly rather than silently drop it. Duplicate ``name``s are allowed —
    ``preset_id`` is identity, not ``name``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=2000)
    setup: WeatherSetup


class WeatherPresetStore:
    """One flat directory of ``<preset_id>.json`` files. No SQLite, no index.

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

    def _path(self, preset_id: str) -> Path:
        return self._root / f"{preset_id}.json"

    def list(self) -> list[SavedWeatherPreset]:
        """Every saved preset, newest ``created_at`` first.

        A file that will not parse is skipped and logged, never raised — the
        "a bad record never stops the browse" rule the profile and camera
        stores already follow.

        Ordering is ``(created_at, preset_id)`` descending. There is no
        ``replace``/``PUT`` for weather presets, so ``created_at`` is always
        the honest key; the id tiebreak covers the same coarse-clock case
        ``core.camera.store.CameraPositionStore.list`` documents — two saves
        close enough together to tie on ``created_at`` still sort stably.
        """
        if not self._root.is_dir():
            return []
        presets: list[SavedWeatherPreset] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                presets.append(
                    SavedWeatherPreset.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValidationError) as exc:
                logger.warning("Skipping unreadable saved weather preset %s: %s", path, exc)
                continue
        presets.sort(key=lambda preset: (preset.created_at, preset.preset_id), reverse=True)
        return presets

    def get(self, preset_id: str) -> SavedWeatherPreset | None:
        """One saved preset, or ``None`` when no file for ``preset_id`` exists.

        Raises :class:`WeatherPresetStoreError` when the file exists but its
        content will not parse — distinct from "not found", which is not an
        error.

        An id not shaped like one this store ever assigns (see
        ``_VALID_PRESET_ID``) answers ``None`` without ever building a
        filesystem path from it.
        """
        if _VALID_PRESET_ID.match(preset_id) is None:
            return None
        path = self._path(preset_id)
        if not path.is_file():
            return None
        try:
            return SavedWeatherPreset.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise WeatherPresetStoreError(
                f"Could not read weather preset {preset_id!r}: {exc}"
            ) from exc
        except ValidationError as exc:
            raise WeatherPresetStoreError(
                f"Stored weather preset {preset_id!r} does not parse: {exc}"
            ) from exc

    def create(self, draft: SavedWeatherPresetCreate) -> SavedWeatherPreset:
        """Assign ``preset_id``/timestamps, write atomically, return the stored preset."""
        now = datetime.now(UTC)
        preset = SavedWeatherPreset(
            preset_id=uuid.uuid4().hex,
            name=draft.name,
            description=draft.description,
            setup=draft.setup,
            created_at=now,
            updated_at=now,
        )
        self._write(preset)
        return preset

    def delete(self, preset_id: str) -> bool:
        """``False`` when the file was already gone. Never raises for that case.

        Same shape-check as :meth:`get` — an id this store could never have
        assigned answers ``False`` without touching the filesystem.
        """
        if _VALID_PRESET_ID.match(preset_id) is None:
            return False
        try:
            self._path(preset_id).unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise WeatherPresetStoreError(
                f"Could not delete weather preset {preset_id!r}: {exc}"
            ) from exc
        return True

    def _write(self, preset: SavedWeatherPreset) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            tmp_path = self._root / f".{preset.preset_id}.tmp"
            tmp_path.write_text(preset.model_dump_json(), encoding="utf-8")
            tmp_path.replace(self._path(preset.preset_id))
        except OSError as exc:
            raise WeatherPresetStoreError(
                f"Could not save weather preset {preset.preset_id!r}: {exc}"
            ) from exc
