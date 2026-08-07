"""The dependency rule, made mechanical.

``core/`` depends only on the ``SimAdapter`` interface and never learns what a
simulator is. That rule has held by review so far; ``core/navdata/`` is the
first part of ``core/`` large enough to break it by accident rather than by
intent — it is the layer closest to real files, real formats and the temptation
to "just check whether X-Plane is running".

Two families of assertion, both by parsing the source rather than importing it,
so a violation is reported as a filename and a line rather than as an
ImportError somewhere else:

1. Nothing under ``core/`` imports a transport, an adapter, or names a dataref.
2. The navdata models import in one direction only (D13 of the design). This is
   what keeps ``Runway.ils`` from turning into a circular import.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CORE_ROOT = Path(__file__).resolve().parents[3] / "core"

#: Modules that speak to something over a wire. None of them belong in core/.
FORBIDDEN_IMPORTS = frozenset({"httpx", "websockets", "SimConnect", "socket", "requests"})

#: Prefixes of dataref names. Dataref strings are adapter vocabulary: if one
#: appears in core/, some logic has started to depend on a specific simulator.
DATAREF_PREFIXES = ("sim/", "laminar/")


def _core_modules() -> list[Path]:
    return sorted(p for p in CORE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Every module name imported by a file, including ``from x.y import z`` as ``x.y``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.add(node.module)
    return names


def _top_level(module: str) -> str:
    return module.split(".", 1)[0]


@pytest.mark.parametrize("path", _core_modules(), ids=lambda p: str(p.name))
def test_core_never_imports_a_transport(path: Path) -> None:
    """No module under core/ opens a socket, directly or through a client library."""
    offenders = {m for m in _imported_modules(_parse(path)) if _top_level(m) in FORBIDDEN_IMPORTS}
    assert not offenders, (
        f"{path.relative_to(CORE_ROOT.parent)} imports {sorted(offenders)}. "
        "core/ talks to no simulator: extend the SimAdapter interface instead."
    )


@pytest.mark.parametrize("path", _core_modules(), ids=lambda p: str(p.name))
def test_core_never_imports_an_adapter(path: Path) -> None:
    """core/ points at the contract; adapters point at the contract. Never the reverse."""
    offenders = {m for m in _imported_modules(_parse(path)) if _top_level(m) == "adapters"}
    assert not offenders, (
        f"{path.relative_to(CORE_ROOT.parent)} imports {sorted(offenders)}. "
        "Only the composition root in server/ may name a concrete adapter."
    )


@pytest.mark.parametrize("path", _core_modules(), ids=lambda p: str(p.name))
def test_core_contains_no_dataref_names(path: Path) -> None:
    """A dataref string in core/ means a simulator's vocabulary has leaked in."""
    tree = _parse(path)
    offenders = sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(DATAREF_PREFIXES)
        }
    )
    assert not offenders, (
        f"{path.relative_to(CORE_ROOT.parent)} contains dataref names {offenders}. "
        "Dataref strings are adapter vocabulary."
    )


def test_navdata_does_not_import_the_sim_contract() -> None:
    """The static world and the live simulator are two different things.

    ``core/navdata/`` has no connection, no lifecycle and no capabilities. If it
    started importing ``core.sim_adapter``, the separation that lets an MSFS
    user read X-Plane navdata — and lets the whole Position Manager run against
    the fake adapter — would be gone.
    """
    navdata_root = CORE_ROOT / "navdata"
    offenders: list[str] = []
    for path in navdata_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if any(m.startswith("core.sim_adapter") for m in _imported_modules(_parse(path))):
            offenders.append(str(path.relative_to(CORE_ROOT.parent)))

    assert not offenders, (
        f"{offenders} import core.sim_adapter. NavdataProvider is not part of SimAdapter: "
        "no navdata method takes or returns a type from the sim contract."
    )


def test_shared_models_do_not_import_navdata_models() -> None:
    """D13: the import between the two model modules runs one way only.

    ``core/navdata/models.py`` imports ``GeoPosition`` from ``core/models.py``.
    If ``core/models.py`` imported anything back — the obvious temptation being
    to put ``Ils`` on the navdata side and pull it in for ``Runway.ils`` — the
    two modules would import each other, and the fix would be ``TYPE_CHECKING``
    guards plus ``model_rebuild()`` calls that every later contributor has to
    remember. Models that cross the seam live in ``core/models.py``.
    """
    imported = _imported_modules(_parse(CORE_ROOT / "models.py"))
    offenders = sorted(m for m in imported if m.startswith("core.navdata"))
    assert not offenders, (
        f"core/models.py imports {offenders}, which closes an import cycle. "
        "Move the shared model into core/models.py instead."
    )
