"""The Training Profiles storage layer — one flat directory of JSON files, no index (D5).

Import-safe: the constructor performs no I/O and does not create the
directory. Every write ensures the directory exists immediately before
writing, and writes atomically (temp file in the same directory, then
``Path.replace`` — the same atomic-publish idiom the navdata index build
uses). Every read treats a missing directory as an empty store.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError, model_validator

from core.profiles.models import ProfileSummary, TrainingProfile, TrainingProfileCreate
from core.scenarios.models import ScenarioDocument

__all__ = ["ProfileStore", "ProfileStoreError"]

logger = logging.getLogger(__name__)

#: Fields a previous export carries that an import must never trust (D7) —
#: reusing them would let an uploaded file collide with, or impersonate, an
#: existing profile.
_IGNORED_ON_IMPORT = frozenset({"profile_id", "created_at", "updated_at", "format_version"})


class ProfileStoreError(RuntimeError):
    """The store itself failed — disk full, permission denied, corrupt content on read.

    Never raised for "not found": :meth:`ProfileStore.get`, :meth:`~ProfileStore.replace`
    and :meth:`~ProfileStore.delete` answer ``None``/``False`` instead, the
    same posture ``core.navdata.provider.NavdataProvider``'s own docstring
    establishes for its own not-found case.
    """


class _ImportDraft(TrainingProfileCreate):
    """``TrainingProfileCreate``, tolerant of the four fields a previous export
    carries (D7) — everything else still hits ``extra="forbid"`` and reports a
    typo exactly as a hand-edited upload should. A ``model_validator(mode="before")``
    strips only the four known keys ahead of field validation, so re-importing
    an exported file (which carries them) and importing a hand-written
    ``TrainingProfileCreate``-shaped file (which does not) both work, and both
    still reject anything else unrecognised.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_export_only_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in _IGNORED_ON_IMPORT}
        return data


def _airport_teaser(scenario: ScenarioDocument) -> str | None:
    """Best-effort teaser off the embedded placement's airport field, if it has one.

    Never a navdata lookup — reads whichever field the placement arm happens
    to carry (``airport_icao`` on five of the seven ``PlacementRequest``
    arms, ``terminal_airport`` on the waypoint arm). ``None`` for a
    coordinate placement, a hold with no airport stated, or a profile with no
    position block at all.
    """
    placement = scenario.position
    if placement is None:
        return None
    icao = getattr(placement, "airport_icao", None) or getattr(placement, "terminal_airport", None)
    return icao.upper() if icao is not None else None


def _summarise(profile: TrainingProfile) -> ProfileSummary:
    return ProfileSummary(
        profile_id=profile.profile_id,
        name=profile.name,
        description=profile.description,
        author=profile.author,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        airport_icao=_airport_teaser(profile.scenario),
    )


class ProfileStore:
    """One flat directory of ``<profile_id>.json`` files. No index (D5)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, profile_id: str) -> Path:
        return self._root / f"{profile_id}.json"

    def list(self) -> list[ProfileSummary]:
        """Every profile, newest ``updated_at`` first.

        A file that fails to parse is skipped and logged, never raised — the
        same "a bad record never stops the browse" rule the navdata index
        build uses for a malformed ``apt.dat`` row.
        """
        if not self._root.is_dir():
            return []
        summaries: list[ProfileSummary] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                profile = TrainingProfile.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError) as exc:
                logger.warning("Skipping unreadable training profile %s: %s", path, exc)
                continue
            summaries.append(_summarise(profile))
        summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
        return summaries

    def get(self, profile_id: str) -> TrainingProfile | None:
        """One profile, or ``None`` when no file for ``profile_id`` exists.

        Raises :class:`ProfileStoreError` when the file exists but its
        content will not parse — distinct from "not found", the same
        distinction :class:`ProfileStoreError`'s own docstring draws.
        """
        path = self._path(profile_id)
        if not path.is_file():
            return None
        try:
            return TrainingProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ProfileStoreError(f"Could not read profile {profile_id!r}: {exc}") from exc
        except ValidationError as exc:
            raise ProfileStoreError(f"Stored profile {profile_id!r} does not parse: {exc}") from exc

    def create(self, draft: TrainingProfileCreate) -> TrainingProfile:
        """Assign ``profile_id``/timestamps, write atomically, return the stored profile."""
        now = datetime.now(UTC)
        profile = TrainingProfile(
            profile_id=uuid.uuid4().hex,
            name=draft.name,
            description=draft.description,
            author=draft.author,
            created_at=now,
            updated_at=now,
            scenario=draft.scenario,
        )
        self._write(profile)
        return profile

    def replace(self, profile_id: str, draft: TrainingProfileCreate) -> TrainingProfile | None:
        """Replace name/description/author/scenario of an existing profile.

        ``None`` when ``profile_id`` does not exist — ``PUT`` never creates
        (D13). Keeps ``profile_id``/``created_at``, bumps ``updated_at``.
        """
        existing = self.get(profile_id)
        if existing is None:
            return None
        profile = TrainingProfile(
            profile_id=existing.profile_id,
            name=draft.name,
            description=draft.description,
            author=draft.author,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
            scenario=draft.scenario,
        )
        self._write(profile)
        return profile

    def delete(self, profile_id: str) -> bool:
        """``False`` when the file was already gone. Never raises for that case."""
        path = self._path(profile_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ProfileStoreError(f"Could not delete profile {profile_id!r}: {exc}") from exc
        return True

    def import_bytes(self, raw: bytes) -> TrainingProfile:
        """Parse ``raw`` as ``TrainingProfileCreate``-shaped JSON and store it under a fresh id.

        Any embedded ``profile_id``/``created_at``/``updated_at``/``format_version``
        in the uploaded document is ignored (D7) — a fresh id is always
        assigned, so re-importing the same export twice produces two
        profiles. Raises :class:`pydantic.ValidationError` on malformed
        content (pydantic's own JSON parser reports invalid JSON syntax as
        part of the same ``ValidationError`` it raises for a schema
        violation, so the router has exactly one exception type to map to
        422); raises :class:`ProfileStoreError` on an I/O failure.
        """
        draft = _ImportDraft.model_validate_json(raw)
        return self.create(draft)

    def export_bytes(self, profile_id: str) -> bytes | None:
        """The canonical ``model_dump_json()`` of the stored profile, or ``None`` if unknown."""
        profile = self.get(profile_id)
        if profile is None:
            return None
        return profile.model_dump_json().encode("utf-8")

    def _write(self, profile: TrainingProfile) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            tmp_path = self._root / f".{profile.profile_id}.tmp"
            tmp_path.write_text(profile.model_dump_json(), encoding="utf-8")
            tmp_path.replace(self._path(profile.profile_id))
        except OSError as exc:
            raise ProfileStoreError(
                f"Could not save profile {profile.profile_id!r}: {exc}"
            ) from exc
