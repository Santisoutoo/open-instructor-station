"""Hard rule 4, made mechanical: no navdata is ever committed.

Navdata is read from the user's own installation and never redistributed. That
rule is the one most likely to be broken **by accident** — a debugging session
copies one airport file "just for a minute", and a ``git add -A`` two hours
later commits it. ``.gitignore`` helps but does not catch a force-added file or
a ``CIFP/`` directory under a new name.

This test walks the repository and fails on anything that looks like navdata
outside the fixture tree. It runs in CI in milliseconds and is the cheapest
insurance in the project.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "navdata"

#: Directories that are never anyone's source: build output, caches, tooling.
SKIPPED_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
     ".ruff_cache", "dist", "build", ".claude"}
)  # fmt: skip

#: Real navdata filenames. Anything matching these outside the fixture tree is
#: somebody's proprietary data.
FORBIDDEN_NAMES = frozenset({"apt.dat", "cycle_info.txt", "cycle.json"})
FORBIDDEN_PREFIXES = ("earth_",)
FORBIDDEN_SUFFIXES = (".sqlite", ".sqlite3")

#: The fixture tree is hand-written and must stay small enough to read. A tree
#: that has grown past this is a tree that has started accumulating real data.
FIXTURE_BUDGET_BYTES = 256 * 1024


def _walk_repository() -> list[Path]:
    """Every file in the repo except build output and the fixture tree itself."""
    found: list[Path] = []
    stack = [REPO_ROOT]
    while stack:
        directory = stack.pop()
        for entry in directory.iterdir():
            if entry.is_dir():
                if entry.name not in SKIPPED_DIRECTORIES and entry != FIXTURE_ROOT:
                    stack.append(entry)
            else:
                found.append(entry)
    return found


def _looks_like_navdata(path: Path) -> bool:
    name = path.name
    return (
        name in FORBIDDEN_NAMES
        or (name.startswith(FORBIDDEN_PREFIXES) and name.endswith(".dat"))
        or name.endswith(FORBIDDEN_SUFFIXES)
    )


def test_no_navdata_outside_the_fixture_tree() -> None:
    """No apt.dat, earth_*.dat, cycle file or SQLite index anywhere in the repository."""
    offenders = sorted(
        str(p.relative_to(REPO_ROOT)) for p in _walk_repository() if _looks_like_navdata(p)
    )
    assert not offenders, (
        f"Navdata-shaped files are committed: {offenders}. Navdata is read from the user's own "
        "install and NEVER redistributed — see hard rule 4. Fixtures belong in "
        "tests/fixtures/navdata/ and must be hand-written or public-domain FAA extracts."
    )


def test_no_cifp_directory_outside_the_fixture_tree() -> None:
    """A CIFP directory anywhere else is a copy of somebody's subscription data."""
    offenders = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.rglob("CIFP")
        if p.is_dir()
        and FIXTURE_ROOT not in p.parents
        and not SKIPPED_DIRECTORIES.intersection(p.parts)
    )
    assert not offenders, f"CIFP directories outside the fixture tree: {offenders}."


def test_fixture_tree_stays_within_its_budget() -> None:
    """Hand-written fixtures stay small. Growth here means real data crept in."""
    if not FIXTURE_ROOT.exists():
        return

    total = sum(p.stat().st_size for p in FIXTURE_ROOT.rglob("*") if p.is_file())
    assert total <= FIXTURE_BUDGET_BYTES, (
        f"tests/fixtures/navdata/ is {total} bytes, over the {FIXTURE_BUDGET_BYTES} budget. "
        "Fixtures are minimal hand-written samples, trimmed to the records a test asserts on."
    )


def test_faa_extracts_carry_their_provenance() -> None:
    """Any real-world records must state where they came from and why that is legal.

    Only the FAA's own CIFP publication may be used — a work of the United
    States Government, in the public domain. Never ``Custom Data/`` (Navigraph
    terms forbid redistribution outright) and never ``Resources/default data/``
    either, which is Laminar's redistribution under Laminar's terms.
    """
    if not FIXTURE_ROOT.exists():
        return

    faa_extracts = list(FIXTURE_ROOT.rglob("faa/*"))
    if not faa_extracts:
        return

    provenance = FIXTURE_ROOT / "PROVENANCE.md"
    assert provenance.is_file(), (
        "Real-world extracts are present but tests/fixtures/navdata/PROVENANCE.md is missing. "
        "Each extract records its source URL, AIRAC cycle, retrieval date and public-domain "
        "status."
    )
