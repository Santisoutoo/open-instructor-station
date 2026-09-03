"""Discover and load cockpit control catalog directories (§6.1, D4).

A catalog is a directory under an adapter's ``cockpit_catalogs/`` root
(``adapters/<sim>/cockpit_catalogs/<catalog-id>/``, never under ``core/`` —
hard rule 2), holding one required ``aircraft.yaml`` (``aircraft``, ``detect``,
``panels``) plus any number of sibling ``*.yaml``/``*.yml`` files contributing
``controls``/``parked``/``setup_overrides``. This mirrors
``core/scenarios/loader.py``'s pattern (one bad directory never takes the
others down) but merges *several* files into *one* document, which the
scenario loader never has to do.

No HTTP, no adapter import, no ``SimAdapter`` instance anywhere near this
module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from core.cockpit.models import (
    CockpitCatalog,
    CockpitCatalogDocument,
    CockpitControlKind,
)

__all__ = [
    "CATALOG_ROOT_FILENAME",
    "CockpitCatalogLoadError",
    "discover_catalog_dirs",
    "load_all_catalogs",
    "load_catalog_dir",
    "publish",
]

#: The one required file per catalog directory.
CATALOG_ROOT_FILENAME = "aircraft.yaml"

#: The two extensions a catalog file may carry.
_CATALOG_SUFFIXES = (".yaml", ".yml")

#: Keys only ``aircraft.yaml`` may carry.
_ROOT_ONLY_KEYS = ("aircraft", "detect", "panels")
#: Keys any file — including the root — may carry, spread across the directory.
_MERGEABLE_KEYS = ("controls", "parked", "setup_overrides")

#: How ``readable`` is derived from a raw control's kind and binding (§3.1's
#: table). Encoder is handled separately: binding-dependent on ``read``.
_ALWAYS_READABLE_KINDS: frozenset[CockpitControlKind] = frozenset({"toggle", "dial", "selector"})
_NEVER_READABLE_KINDS: frozenset[CockpitControlKind] = frozenset({"press"})


class CockpitCatalogLoadError(Exception):
    """One directory failed to load.

    Carries ``.path`` and ``.error`` (``ScenarioLoadError``'s shape).
    """

    def __init__(self, path: Path, error: Exception) -> None:
        self.path = path
        self.error = error
        super().__init__(f"{path}: {error}")


def discover_catalog_dirs(root: Path) -> tuple[Path, ...]:
    """Every immediate subdirectory of ``root`` containing ``aircraft.yaml``, sorted by name.

    A missing root is empty, not an error.
    """
    if not root.is_dir():
        return ()
    dirs = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / CATALOG_ROOT_FILENAME).is_file()
    ]
    return tuple(sorted(dirs, key=lambda path: path.name))


def _catalog_files(directory: Path) -> tuple[Path, ...]:
    """Every ``*.yaml``/``*.yml`` directly under ``directory``, sorted by name."""
    if not directory.is_dir():
        return ()
    files = [
        path for path in directory.iterdir() if path.is_file() and path.suffix in _CATALOG_SUFFIXES
    ]
    return tuple(sorted(files, key=lambda path: path.name))


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CockpitCatalogLoadError(path, exc) from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CockpitCatalogLoadError(
            path, ValueError("A catalog file must contain a YAML mapping at the top level.")
        )
    return raw


def _check_no_stated_readable(path: Path, controls: object) -> None:
    """Reject a file that states ``readable`` explicitly — the loader derives it."""
    if not isinstance(controls, list):
        return
    for entry in controls:
        if isinstance(entry, dict) and "readable" in entry:
            raise CockpitCatalogLoadError(
                path,
                ValueError(
                    f"Control {entry.get('control_id')!r} states 'readable' explicitly; "
                    "the loader derives it from the binding."
                ),
            )


def _derive_readable(entry: dict[str, Any]) -> bool:
    kind = entry.get("kind")
    if kind in _NEVER_READABLE_KINDS:
        return False
    if kind in _ALWAYS_READABLE_KINDS:
        return True
    if kind == "encoder":
        binding = entry.get("binding")
        return isinstance(binding, dict) and bool(binding.get("read"))
    # An invalid/missing kind is left to pydantic's own validation to reject.
    return False


def load_catalog_dir(directory: Path) -> CockpitCatalogDocument:
    """Merge ``aircraft.yaml`` with every other ``*.yaml``/``*.yml`` file in ``directory``.

    Raises :class:`CockpitCatalogLoadError` on: a missing root file, a key
    appearing in the wrong file, a duplicate ``control_id``/``setup_overrides``
    key across files, a directory name that differs from
    ``aircraft.catalog_id``, ``readable`` stated in a file, or any pydantic
    ``ValidationError`` — every one wrapped, never raised raw.
    """
    root_path = directory / CATALOG_ROOT_FILENAME
    if not root_path.is_file():
        raise CockpitCatalogLoadError(
            root_path, FileNotFoundError(f"No {CATALOG_ROOT_FILENAME} in {directory}.")
        )

    merged: dict[str, Any] = {"controls": [], "parked": [], "setup_overrides": {}}
    seen_control_ids: set[str] = set()

    for path in _catalog_files(directory):
        raw = _read_yaml(path)
        is_root = path.name == CATALOG_ROOT_FILENAME

        if is_root:
            for key in _ROOT_ONLY_KEYS:
                if key not in raw:
                    raise CockpitCatalogLoadError(
                        path, ValueError(f"{CATALOG_ROOT_FILENAME} must declare {key!r}.")
                    )
            merged["aircraft"] = raw["aircraft"]
            merged["detect"] = raw["detect"]
            merged["panels"] = raw["panels"]
        else:
            for key in _ROOT_ONLY_KEYS:
                if key in raw:
                    raise CockpitCatalogLoadError(
                        path,
                        ValueError(
                            f"{key!r} may only be declared in {CATALOG_ROOT_FILENAME}, not "
                            f"in {path.name!r}."
                        ),
                    )

        controls = raw.get("controls", [])
        _check_no_stated_readable(path, controls)
        if isinstance(controls, list):
            for entry in controls:
                if not isinstance(entry, dict):
                    continue
                control_id = entry.get("control_id")
                if control_id in seen_control_ids:
                    raise CockpitCatalogLoadError(
                        path, ValueError(f"Duplicate control_id {control_id!r} across files.")
                    )
                if isinstance(control_id, str):
                    seen_control_ids.add(control_id)
                merged["controls"].append({**entry, "readable": _derive_readable(entry)})

        parked = raw.get("parked", [])
        if isinstance(parked, list):
            for entry in parked:
                if isinstance(entry, dict):
                    parked_id = entry.get("control_id")
                    if parked_id in seen_control_ids:
                        raise CockpitCatalogLoadError(
                            path,
                            ValueError(f"Duplicate control_id {parked_id!r} across files."),
                        )
                    if isinstance(parked_id, str):
                        seen_control_ids.add(parked_id)
                merged["parked"].append(entry)

        overrides = raw.get("setup_overrides", {})
        if isinstance(overrides, dict):
            for field_name, control_id in overrides.items():
                if field_name in merged["setup_overrides"]:
                    raise CockpitCatalogLoadError(
                        path,
                        ValueError(f"Duplicate setup_overrides key {field_name!r} across files."),
                    )
                merged["setup_overrides"][field_name] = control_id

    if "aircraft" not in merged:
        raise CockpitCatalogLoadError(
            root_path, ValueError(f"{CATALOG_ROOT_FILENAME} must declare 'aircraft'.")
        )

    try:
        document = CockpitCatalogDocument.model_validate(merged)
    except ValidationError as exc:
        raise CockpitCatalogLoadError(directory, exc) from exc

    if document.aircraft.catalog_id != directory.name:
        raise CockpitCatalogLoadError(
            root_path,
            ValueError(
                f"Directory {directory.name!r} does not match aircraft.catalog_id "
                f"{document.aircraft.catalog_id!r}."
            ),
        )

    return document


def load_all_catalogs(
    root: Path,
) -> tuple[tuple[CockpitCatalogDocument, ...], tuple[CockpitCatalogLoadError, ...]]:
    """Scan and load every catalog directory under ``root``. Never raises on one bad directory."""
    loaded: list[CockpitCatalogDocument] = []
    errors: list[CockpitCatalogLoadError] = []
    for directory in discover_catalog_dirs(root):
        try:
            loaded.append(load_catalog_dir(directory))
        except CockpitCatalogLoadError as exc:
            errors.append(exc)
    return tuple(loaded), tuple(errors)


def publish(
    document: CockpitCatalogDocument, *, revision: int, detection_note: str | None
) -> CockpitCatalog:
    """The binding-free projection (D3): ``supported=True``, panels sorted by
    ``order``, controls in file order with ``.spec`` applied.
    """
    return CockpitCatalog(
        supported=True,
        reason=None,
        aircraft=document.aircraft,
        revision=revision,
        detection_note=detection_note,
        panels=sorted(document.panels, key=lambda panel: panel.order),
        controls=[control.spec for control in document.controls],
        parked=list(document.parked),
    )
