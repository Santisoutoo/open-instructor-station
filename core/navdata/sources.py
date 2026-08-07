"""Finding the user's data files, and deciding which copy of each one wins.

Three jobs, all of them pure functions over a filesystem path:

* :func:`discover_xplane_root` — where the installation is.
* :func:`resolve_data_file` — which copy of a given file to read.
* :func:`read_cycle_info` — which AIRAC cycle that data is.

Nothing here parses navdata; it only decides what to open. Every path is opened
read-only, and nothing is ever written back into the user's install.
"""

from __future__ import annotations

import os
import platform
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

__all__ = [
    "APT_DAT_RELATIVE",
    "CycleInfo",
    "candidate_roots",
    "cifp_file",
    "discover_xplane_root",
    "is_valid_xplane_root",
    "read_cycle_info",
    "resolve_data_file",
]

#: The scenery file airports come from. Not subject to Custom Data precedence:
#: it is scenery, not navdata.
APT_DAT_RELATIVE = Path("Global Scenery/Global Airports/Earth nav data/apt.dat")

_CUSTOM_DATA = Path("Custom Data")
_DEFAULT_DATA = Path("Resources/default data")

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip

_CYCLE_LINE = re.compile(r"AIRAC\s+cycle\s*:\s*(\S+)", re.IGNORECASE)
_VALID_LINE = re.compile(
    r"Valid\s*\(from/to\)\s*:\s*(\d{2}/[A-Z]{3}/\d{4})\s*-\s*(\d{2}/[A-Z]{3}/\d{4})",
    re.IGNORECASE,
)
_CYCLE_JSON = re.compile(r'"cycle"\s*:\s*"(\d+)"')
_HEADER_CYCLE = re.compile(r"data\s+cycle\s+(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class CycleInfo:
    """The AIRAC cycle of an installation, and where that answer came from."""

    cycle: str
    valid_from: date | None = None
    valid_to: date | None = None
    source: str = ""


def is_valid_xplane_root(root: Path) -> bool:
    """True when ``root`` looks like a complete X-Plane 12 installation.

    Both markers are required, and the navdata one is checked on the
    ``Resources/`` side specifically: ``Custom Data/`` is legitimately empty on
    a stock install, so testing it would reject a perfectly good tree. Checking
    two files in two different subtrees also catches a partially copied one.
    """
    try:
        return (root / _DEFAULT_DATA / "earth_nav.dat").is_file() and (
            root / APT_DAT_RELATIVE
        ).is_file()
    except OSError:
        # An unreadable or disconnected network path is "not an install", not a crash.
        return False


def candidate_roots() -> Iterator[Path]:
    """Yield installation candidates in priority order, best first.

    The order matters more than the list: X-Plane's own installation registry
    is a file the simulator itself maintains, so it is right far more often
    than any guess about drive letters.
    """
    registry = _install_registry_path()
    if registry is not None and registry.is_file():
        try:
            lines = registry.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            entry = line.strip()
            if entry:
                yield Path(entry)

    yield from _well_known_roots()


def discover_xplane_root(configured: Path | None = None) -> Path | None:
    """Find the user's X-Plane 12 installation.

    Args:
        configured: An explicitly configured path. When set it is the **only**
            candidate considered: a user who configured a path and silently got
            someone else's install would never work out why. An invalid
            configured path returns ``None`` so the caller can report it as a
            configuration error with the path in the message.

    Returns:
        The first candidate that validates, or ``None``.
    """
    if configured is not None:
        return configured if is_valid_xplane_root(configured) else None

    for candidate in candidate_roots():
        if is_valid_xplane_root(candidate):
            return candidate
    return None


def resolve_data_file(root: Path, name: str) -> Path | None:
    """Resolve one navdata file, ``Custom Data/`` winning over ``Resources/default data/``.

    **Per file, and this is not pedantry.** On a real install
    ``Custom Data/CIFP/`` holds ~14 900 airports while
    ``Resources/default data/CIFP/`` holds ~15 900: roughly a thousand airports
    have procedures *only* in the default data. A directory-level rule would
    silently lose every one of them, so the rule applies to each file — including
    each ``CIFP/<ICAO>.dat`` — individually.

    Zero-byte files are treated as absent, because some navdata installers leave
    empty placeholders behind and reading one produces "this airport has no
    procedures" rather than an error.

    Args:
        root: The installation root.
        name: A path relative to the data directory, e.g. ``"earth_nav.dat"``
            or ``"CIFP/LEMD.dat"``.

    Returns:
        The winning path, or ``None`` when neither copy exists.
    """
    custom = root / _CUSTOM_DATA / name
    if _is_non_empty_file(custom):
        return custom
    default = root / _DEFAULT_DATA / name
    if _is_non_empty_file(default):
        return default
    return None


def cifp_file(root: Path, icao: str) -> Path | None:
    """Resolve one airport's CIFP file, honouring per-file precedence."""
    return resolve_data_file(root, f"CIFP/{icao.strip().upper()}.dat")


def read_cycle_info(root: Path) -> CycleInfo | None:
    """Read the AIRAC cycle, trying every place it is published.

    ``cycle_info.txt`` is the documented source but is **not guaranteed to
    exist** — on a real install it is present in ``Custom Data/`` and absent
    from ``Resources/default data/``. So this walks a ladder, and every rung of
    it was verified against a real installation rather than invented
    defensively:

    1. ``Custom Data/cycle_info.txt``
    2. ``Resources/default data/cycle_info.txt``
    3. ``Custom Data/cycle.json``
    4. the header line of the resolved ``earth_nav.dat``

    Returns:
        The cycle, or ``None`` when no rung answered. ``None`` is survivable:
        the cache key degrades to the file fingerprints alone and the provider
        still works — it just cannot tell the user which cycle they are on.
    """
    for relative in (_CUSTOM_DATA / "cycle_info.txt", _DEFAULT_DATA / "cycle_info.txt"):
        info = _parse_cycle_info_text(_read_text(root / relative), str(relative))
        if info is not None:
            return info

    info = _parse_cycle_json(_read_text(root / _CUSTOM_DATA / "cycle.json"))
    if info is not None:
        return info

    earth_nav = resolve_data_file(root, "earth_nav.dat")
    if earth_nav is not None:
        return _parse_cycle_header(_read_head(earth_nav))

    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_non_empty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _install_registry_path() -> Path | None:
    """Where X-Plane records its own installations, per platform."""
    system = platform.system()
    if system == "Windows":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            return None
        return Path(local_appdata) / "x-plane_install_12.txt"
    if system == "Darwin":
        return Path.home() / "Library" / "Preferences" / "x-plane_install_12.txt"
    return Path.home() / ".x-plane" / "x-plane_install_12.txt"


def _well_known_roots() -> Iterator[Path]:
    """Cheap guesses for the common installs, used only when the registry misses."""
    system = platform.system()
    if system == "Windows":
        for drive in ("C:", "D:", "E:"):
            yield Path(f"{drive}/X-Plane 12")
            yield Path(f"{drive}/SteamLibrary/steamapps/common/X-Plane 12")
        return
    if system == "Darwin":
        yield Path("/Applications/X-Plane 12")
    yield Path.home() / "X-Plane 12"
    yield Path.home() / ".steam/steam/steamapps/common/X-Plane 12"


def _read_text(path: Path) -> str | None:
    try:
        if not _is_non_empty_file(path):
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_head(path: Path, max_bytes: int = 4096) -> str | None:
    """Read only the first few KB — the header is line 2 of a 3.7 MB file."""
    try:
        with path.open("rb") as handle:
            return handle.read(max_bytes).decode("utf-8", errors="replace")
    except OSError:
        return None


def _parse_cycle_info_text(text: str | None, source: str) -> CycleInfo | None:
    if not text:
        return None
    match = _CYCLE_LINE.search(text)
    if match is None:
        return None
    valid_from, valid_to = _parse_validity(text)
    return CycleInfo(cycle=match.group(1), valid_from=valid_from, valid_to=valid_to, source=source)


def _parse_validity(text: str) -> tuple[date | None, date | None]:
    match = _VALID_LINE.search(text)
    if match is None:
        return None, None
    return _parse_ddmmmyyyy(match.group(1)), _parse_ddmmmyyyy(match.group(2))


def _parse_ddmmmyyyy(value: str) -> date | None:
    """Parse ``09/JUL/2026``. Returns ``None`` rather than raising on anything odd."""
    parts = value.split("/")
    if len(parts) != 3:
        return None
    day, month_name, year = parts
    month = _MONTHS.get(month_name.upper())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _parse_cycle_json(text: str | None) -> CycleInfo | None:
    """Read ``cycle.json`` with a regex rather than ``json.loads``.

    One field is wanted out of a file written by third-party installers; a
    trailing comma or a stray byte must degrade to the next rung of the ladder,
    not raise.
    """
    if not text:
        return None
    match = _CYCLE_JSON.search(text)
    if match is None:
        return None
    return CycleInfo(cycle=match.group(1), source="Custom Data/cycle.json")


def _parse_cycle_header(text: str | None) -> CycleInfo | None:
    """Read the cycle out of ``1200 Version - data cycle 2607, build 20260701, …``."""
    if not text:
        return None
    match = _HEADER_CYCLE.search(text)
    if match is None:
        return None
    return CycleInfo(cycle=match.group(1), source="earth_nav.dat header")
