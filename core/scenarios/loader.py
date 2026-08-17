"""Discover and load scenario YAML files — the exit-criterion mechanism.

Per ``docs/designs/scenario-generator.md`` §6.1, D1, D2: a scenario is a
``*.yaml``/``*.yml`` file under :data:`SCENARIOS_DIR`, discovered by a plain
directory scan. The filename stem **is** the scenario id (lowercase
kebab-case, enforced by :data:`SCENARIO_ID_PATTERN`) — there is no registry
mapping ids to files, and "add a scenario" is literally "add a correctly
named file".

``directory`` is a parameter on every function here, never baked into a
function body, precisely so a test can point the loader at a fixture
directory nothing else in the codebase names (§8.1's exit-criterion test) —
the literal proof that discovery is a scan, not a hardcoded list.

``core/``-only: no HTTP, no adapter import, no ``SimAdapter`` instance
anywhere near this module (D6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from core.scenarios.models import ScenarioDocument

__all__ = [
    "SCENARIOS_DIR",
    "SCENARIO_ID_PATTERN",
    "LoadedScenario",
    "ScenarioLoadError",
    "discover_scenario_files",
    "load_all_scenarios",
    "load_scenario_file",
]

#: Shipped, read-only scenarios. Co-located with the manager that owns the
#: loader, the same shape as ``core/weather/presets.py``'s data (D1).
SCENARIOS_DIR: Path = Path(__file__).parent / "data"

#: Lowercase kebab-case, enforced on the filename stem — the scenario id (D2).
SCENARIO_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: The two extensions a scenario file may carry.
_SCENARIO_SUFFIXES = (".yaml", ".yml")


@dataclass(frozen=True)
class LoadedScenario:
    """One scenario, parsed and validated. ``id`` is the filename stem (D2)."""

    id: str
    document: ScenarioDocument
    source_path: Path


class ScenarioLoadError(Exception):
    """One file failed to parse or validate.

    Carried, never raised past the loader itself — one bad file must not take
    down the other thirteen. :attr:`path` and :attr:`error` are kept apart
    (rather than only formatted into the message) so a caller can report the
    file and the underlying cause separately if it wants to.
    """

    def __init__(self, path: Path, error: Exception) -> None:
        self.path = path
        self.error = error
        super().__init__(f"{path}: {error}")


def discover_scenario_files(directory: Path = SCENARIOS_DIR) -> tuple[Path, ...]:
    """Every ``*.yaml``/``*.yml`` directly under ``directory``, sorted by stem.

    Sorted for a deterministic manifest order. Pure ``pathlib`` globbing
    (ruff's ``PTH`` rule). A directory that does not exist yet (a fixture
    directory a test has not created, or a shipped ``data/`` before Track B
    lands) is treated as empty rather than raised on — there is nothing
    dubious about "no scenarios here yet".
    """
    if not directory.is_dir():
        return ()
    files = [
        path for path in directory.iterdir() if path.is_file() and path.suffix in _SCENARIO_SUFFIXES
    ]
    # Tie-broken by the full filename so two files sharing a stem (the
    # .yaml/.yml collision case) sort deterministically rather than by
    # filesystem iteration order.
    return tuple(sorted(files, key=lambda path: (path.stem, path.name)))


def load_scenario_file(path: Path) -> LoadedScenario:
    """Parse and validate one file.

    Raises :class:`ScenarioLoadError` — never a raw :class:`yaml.YAMLError`
    or pydantic :class:`~pydantic.ValidationError` — so every caller has one
    error type to handle. A stem that does not match
    :data:`SCENARIO_ID_PATTERN` is itself a :class:`ScenarioLoadError`: an id
    is enforced before the content is even read.
    """
    stem = path.stem
    if not SCENARIO_ID_PATTERN.match(stem):
        raise ScenarioLoadError(
            path,
            ValueError(
                f"{stem!r} is not a valid scenario id: expected lowercase "
                f"kebab-case, matching {SCENARIO_ID_PATTERN.pattern!r}."
            ),
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioLoadError(path, exc) from exc

    try:
        document = ScenarioDocument.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioLoadError(path, exc) from exc

    return LoadedScenario(id=stem, document=document, source_path=path)


def load_all_scenarios(
    directory: Path = SCENARIOS_DIR,
) -> tuple[tuple[LoadedScenario, ...], tuple[ScenarioLoadError, ...]]:
    """Scan and load every file in one pass.

    Never raises on a single bad file: a typo in one scenario does not hold
    the rest hostage — every failure is collected into the second element of
    the return tuple instead. A stem present under both ``.yaml`` and
    ``.yml`` is a load error for the second one found (in the deterministic
    order :func:`discover_scenario_files` returns) — two files cannot
    honestly share one id.
    """
    loaded: list[LoadedScenario] = []
    errors: list[ScenarioLoadError] = []
    seen_ids: set[str] = set()

    for path in discover_scenario_files(directory):
        stem = path.stem
        if stem in seen_ids:
            errors.append(
                ScenarioLoadError(
                    path,
                    ValueError(f"Scenario id {stem!r} is defined by more than one file."),
                )
            )
            continue
        seen_ids.add(stem)
        try:
            loaded.append(load_scenario_file(path))
        except ScenarioLoadError as exc:
            errors.append(exc)

    return tuple(loaded), tuple(errors)
