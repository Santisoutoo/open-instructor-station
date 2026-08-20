"""Building the SQLite index, and the cache lifecycle around it.

The build itself is the easy part. What is written down here is the lifecycle,
because every rule in it is invisible when it works and expensive to debug when
it does not:

* **The cache key is a fingerprint tuple, not the AIRAC cycle alone.** The cycle
  is the primary component, but ``apt.dat`` lives under ``Global Scenery/`` and
  is not covered by any cycle — it changes when the user updates X-Plane, with
  no cycle bump at all — and a :data:`~core.navdata.schema.SCHEMA_VERSION` bump
  by this project must force a rebuild too. So the key is
  ``(schema version, cycle, root, {role: (path, size, mtime)})``, recomputed in
  microseconds from a handful of ``stat()`` calls.
* **A published file is never overwritten** (D15). Each build writes a **new
  generation** and readers reopen on an epoch bump. Replacing the file live
  connections have open is a ``PermissionError`` on Windows at best, and at
  worst it *succeeds* — and readers that opened with ``immutable=1`` have
  promised SQLite the bytes will not change.
* **Two processes are serialised by an OS advisory lock**, not by "does
  ``build.lock`` exist?". A lock whose mere existence means "locked" is orphaned
  by exactly the events most likely to interrupt a two-minute build — a crash, a
  power cut, a ``SIGKILL`` — and every later start then waits forever on a
  holder that no longer exists. A kernel-held lock dies with its process, so
  that failure mode does not exist.
* **Cancellation is checked per insert batch**, publishes nothing, and leaves
  the previously published generation exactly as it was.
"""

from __future__ import annotations

import os
import platform
import re
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import quote

from core.navdata.models import IndexProgress
from core.navdata.normalize import normalize_search_text
from core.navdata.provider import NavdataIndexError
from core.navdata.schema import (
    FINALISE_PRAGMAS,
    INSERT_AIRPORT,
    INSERT_BATCH_SIZE,
    INSERT_FIX,
    INSERT_HOLD,
    INSERT_META,
    INSERT_NAVAID,
    INSERT_PARKING,
    INSERT_RUNWAY,
    INSERT_SOURCE_FILE,
    SCHEMA_VERSION,
    apply_schema,
    prepare_for_build,
    read_user_version,
)
from core.navdata.sources import APT_DAT_RELATIVE, CycleInfo, read_cycle_info, resolve_data_file
from core.navdata.xplane_native.apt import ParsedAirport, iter_airports
from core.navdata.xplane_native.earth import parse_earth_fix, parse_earth_hold, parse_earth_nav

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

__all__ = [
    "LOCK_TIMEOUT_S",
    "BuildLockTimeout",
    "BuildStats",
    "IndexStage",
    "ProgressSink",
    "ResolvedSources",
    "SourceFile",
    "advisory_lock",
    "build_index",
    "cache_directory",
    "generation_files",
    "next_generation_path",
    "read_cache_key",
    "read_only_uri",
    "resolve_sources",
    "sweep_generations",
]

#: Comfortably above the 60-120 s a full build takes on a real install. A loser
#: that times out does **not** build in parallel: it reports an error naming the
#: situation, and the rebuild endpoint stays available.
LOCK_TIMEOUT_S = 180.0

#: Roles recorded in ``source_file`` and fingerprinted into the cache key.
_REQUIRED_ROLES = ("apt", "earth_nav", "earth_fix")
_OPTIONAL_ROLES = ("earth_hold",)

_GENERATION_NAME = re.compile(
    r"^navdata-(?P<cycle>[^-]*)-v(?P<version>\d+)-g(?P<generation>\d+)\.sqlite$"
)

#: Stage weights, so the bar advances in proportion to the work behind it.
#: ``apt.dat`` is 380 MB against 26 MB for everything else, and a bar that
#: crawls for a minute and then jumps to 100% teaches the user to distrust it.
_STAGE_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("airports", 0.55),
    ("runways", 0.05),
    ("parking", 0.05),
    ("navaids", 0.08),
    ("fixes", 0.20),
    ("holds", 0.04),
    ("finalising", 0.03),
)

IndexStage = str
ProgressSink = Callable[[IndexProgress], None]

#: No more than one frame per this many seconds, or per this much overall
#: progress, whichever comes first — plus one unconditional frame at every stage
#: boundary so no stage is invisible. ``apt.dat`` is 12.35 M lines; a frame per
#: line, or per thousand lines, is a denial of service on the WebSocket for a
#: bar that moves in pixels.
_MIN_FRAME_INTERVAL_S = 0.5
_MIN_FRAME_FRACTION = 0.01


class BuildLockTimeout(RuntimeError):
    """Another process held the build lock for longer than the timeout."""

    def __init__(self, path: Path, timeout_s: float) -> None:
        self.path = path
        self.timeout_s = timeout_s
        super().__init__(
            f"Another process has been building the navigation index for more than "
            f"{timeout_s:.0f} s (lock: {path}). Nothing was rebuilt."
        )


@dataclass(frozen=True)
class SourceFile:
    """One indexed source file and the fingerprint that decides staleness.

    ``(size, mtime_ns)`` rather than a content hash: hashing 380 MB on every
    start-up would cost far more than the check saves, and these are files the
    user replaces wholesale through an installer.
    """

    role: str
    path: Path
    size_bytes: int
    mtime_ns: int

    @property
    def fingerprint(self) -> str:
        return f"{self.role}={self.path}:{self.size_bytes}:{self.mtime_ns}"


@dataclass(frozen=True)
class ResolvedSources:
    """Which file won for each role, plus the cycle they belong to."""

    root: Path
    files: tuple[SourceFile, ...]
    cycle: CycleInfo | None
    missing_roles: tuple[str, ...]

    def path(self, role: str) -> Path | None:
        return next((f.path for f in self.files if f.role == role), None)

    @property
    def cache_key(self) -> str:
        """The whole invalidation rule, as one comparable string.

        Cycle change, scenery update and schema bump all land here, so there is
        one mechanism to reason about rather than three.
        """
        cycle = self.cycle.cycle if self.cycle is not None else ""
        parts = "|".join(sorted(f.fingerprint for f in self.files))
        return f"v{SCHEMA_VERSION}|cycle={cycle}|root={self.root}|{parts}"


@dataclass(frozen=True)
class BuildStats:
    """What a completed build produced, for ``status()`` and the ``meta`` table."""

    airport_count: int
    runway_count: int
    parking_count: int
    navaid_count: int
    fix_count: int
    hold_count: int
    skipped_record_count: int
    duration_s: float


# ---------------------------------------------------------------------------
# Source resolution and the cache key
# ---------------------------------------------------------------------------


def resolve_sources(root: Path) -> ResolvedSources:
    """Resolve every indexed file under ``root``, honouring per-file precedence.

    ``apt.dat`` is exempt from the ``Custom Data/`` rule: it is **scenery, not
    navdata**, and Phase 1 reads exactly one copy of it — the Global Airports
    file. Custom Scenery overrides are an explicit non-goal with their own
    issue, because doing them correctly means honouring pack order and
    per-airport replacement semantics, and it multiplies the build the user
    waits for.
    """
    found: list[SourceFile] = []
    missing: list[str] = []

    candidates: list[tuple[str, Path | None]] = [("apt", root / APT_DAT_RELATIVE)]
    candidates += [
        (role, resolve_data_file(root, f"{role}.dat"))
        for role in ("earth_nav", "earth_fix", "earth_hold")
    ]

    for role, path in candidates:
        stamped = _stat(role, path)
        if stamped is None:
            missing.append(role)
        else:
            found.append(stamped)

    cycle = read_cycle_info(root)
    if cycle is not None and cycle.source:
        cycle_file = _stat("cycle_info", root / cycle.source)
        if cycle_file is not None:
            found.append(cycle_file)

    return ResolvedSources(
        root=root,
        files=tuple(found),
        cycle=cycle,
        missing_roles=tuple(r for r in missing if r in _REQUIRED_ROLES),
    )


def _stat(role: str, path: Path | None) -> SourceFile | None:
    if path is None:
        return None
    try:
        info = path.stat()
    except OSError:
        return None
    if not path.is_file() or info.st_size == 0:
        return None
    return SourceFile(role=role, path=path, size_bytes=info.st_size, mtime_ns=info.st_mtime_ns)


# ---------------------------------------------------------------------------
# Cache location and generations (D15)
# ---------------------------------------------------------------------------


def cache_directory(override: Path | None = None, *, environ: dict[str, str] | None = None) -> Path:
    """Where the index lives: the platform user-cache directory.

    **Never in the repository and never inside the X-Plane install**, which may
    sit on a read-only or network drive and is not ours to write to.
    """
    if override is not None:
        return override

    env = environ if environ is not None else _environment()
    configured = env.get("OIS_NAVDATA_CACHE_DIR")
    if configured:
        return Path(configured)

    # ``platform.system()`` rather than ``sys.platform``: this is a runtime
    # branch over three real destinations, and a type checker that narrows
    # ``sys.platform`` to the host it is running on declares the other two
    # unreachable. ``sys.platform`` stays where it belongs — deciding which
    # locking module to import.
    system = platform.system()
    if system == "Windows":
        base = env.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "OpenInstructorStation" / "navdata"
    if system == "Darwin":
        return Path.home() / "Library" / "Caches" / "OpenInstructorStation" / "navdata"

    xdg = env.get("XDG_CACHE_HOME")
    root = Path(xdg) if xdg else Path.home() / ".cache"
    return root / "open-instructor-station" / "navdata"


def _environment() -> dict[str, str]:
    return dict(os.environ)


def generation_files(cache_dir: Path) -> list[tuple[int, Path]]:
    """Every published generation in the cache directory, oldest first."""
    try:
        entries = list(cache_dir.iterdir())
    except OSError:
        return []

    found: list[tuple[int, Path]] = []
    for entry in entries:
        match = _GENERATION_NAME.match(entry.name)
        if match is not None and int(match.group("version")) == SCHEMA_VERSION:
            found.append((int(match.group("generation")), entry))
    return sorted(found)


def next_generation_path(cache_dir: Path, cycle: str | None) -> Path:
    """The filename the next build publishes to — always one nobody has open.

    A rebuild on an unchanged install produces the same cycle and the same
    schema version as the file already published. Without the generation number
    the build would rename onto the exact path live thread-local connections
    hold open, which is a ``PermissionError`` on Windows at best and undefined
    behaviour under ``immutable=1`` at worst.
    """
    latest = generation_files(cache_dir)
    generation = (latest[-1][0] + 1) if latest else 1
    return cache_dir / f"navdata-{_cycle_token(cycle)}-v{SCHEMA_VERSION}-g{generation}.sqlite"


def sweep_generations(cache_dir: Path, keep: Path | None) -> None:
    """Unlink superseded generations, so the directory holds one file in steady state.

    On Windows an unlink can fail while a handle lingers. That is not surfaced:
    a stale file wastes disk, it does not break anything, and the next start-up
    sweeps it.
    """
    for _, path in generation_files(cache_dir):
        if keep is not None and path == keep:
            continue
        try:
            path.unlink()
        except OSError:
            continue


def _cycle_token(cycle: str | None) -> str:
    """A filename-safe cycle. A missing cycle is survivable, so it gets a name."""
    if not cycle:
        return "nocycle"
    cleaned = "".join(ch for ch in cycle if ch.isalnum())
    return cleaned or "nocycle"


def read_only_uri(path: Path) -> str:
    """The URI every reader opens a published cache with.

    ``immutable=1`` is load-bearing rather than an optimisation: it tells SQLite
    the file cannot change underneath it, which skips all locking and ``-shm``
    handling — no lock files, no write permission needed in the cache directory.
    It is a **promise**, and generations (D15) are what make the promise true.
    """
    posix = path.as_posix()
    if not posix.startswith("/"):
        posix = f"/{posix}"
    return f"file://{quote(posix, safe='/:')}?mode=ro&immutable=1"


def read_cache_key(path: Path) -> str | None:
    """The cache key stamped into a published file, or ``None`` if it is unusable."""
    try:
        connection = sqlite3.connect(read_only_uri(path), uri=True)
    except sqlite3.Error:
        return None
    try:
        if read_user_version(connection) != SCHEMA_VERSION:
            return None
        row = connection.execute("SELECT value FROM meta WHERE key = 'cache_key'").fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return str(row[0]) if row is not None else None


# ---------------------------------------------------------------------------
# The advisory lock
# ---------------------------------------------------------------------------


@contextmanager
def advisory_lock(
    path: Path, *, timeout_s: float = LOCK_TIMEOUT_S, poll_s: float = 0.2
) -> Iterator[None]:
    """Serialise builds across processes with a lock the **kernel** holds.

    Raises:
        BuildLockTimeout: The lock was still held when the timeout expired.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            if _try_lock(handle):
                break
            if time.monotonic() >= deadline:
                raise BuildLockTimeout(path, timeout_s)
            time.sleep(poll_s)
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


def _try_lock(handle: Any) -> bool:
    handle.seek(0)
    try:
        if sys.platform == "win32":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: Any) -> None:
    handle.seek(0)
    try:
        if sys.platform == "win32":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # The kernel releases it when the handle closes anyway.
        pass


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


class _Progress:
    """Throttles frames at the source and turns stage-local progress into overall."""

    def __init__(self, sink: ProgressSink | None) -> None:
        self._sink = sink
        self._index = 0
        self._base = 0.0
        self._weight = 0.0
        self._stage = _STAGE_WEIGHTS[0][0]
        self._last_time = 0.0
        self._last_fraction = -1.0

    def enter(self, stage: str) -> None:
        """Start a stage and emit one unconditional frame, so no stage is invisible."""
        base = 0.0
        for index, (name, weight) in enumerate(_STAGE_WEIGHTS, start=1):
            if name == stage:
                self._index, self._base, self._weight, self._stage = index, base, weight, name
                break
            base += weight
        self._emit(0.0, None, forced=True)

    def update(self, within_stage: float, detail: str | None = None) -> None:
        self._emit(min(max(within_stage, 0.0), 1.0), detail, forced=False)

    def _emit(self, within_stage: float, detail: str | None, *, forced: bool) -> None:
        if self._sink is None:
            return
        fraction = min(self._base + self._weight * within_stage, 1.0)
        now = time.monotonic()
        if not forced and (
            now - self._last_time < _MIN_FRAME_INTERVAL_S
            and fraction - self._last_fraction < _MIN_FRAME_FRACTION
        ):
            return
        self._last_time = now
        self._last_fraction = fraction
        self._sink(
            IndexProgress(
                stage=self._stage,  # type: ignore[arg-type]
                stage_index=max(self._index, 1),
                stage_count=len(_STAGE_WEIGHTS),
                fraction=fraction,
                detail=detail,
            )
        )


class _Batch:
    """Accumulates rows and flushes them with ``executemany``.

    The batch boundary is also where cancellation is checked: often enough to
    react in a fraction of a second, never often enough to cost anything
    per row.
    """

    def __init__(self, connection: sqlite3.Connection, statement: str) -> None:
        self._connection = connection
        self._statement = statement
        self._rows: list[tuple[Any, ...]] = []
        self.count = 0

    def add(self, row: tuple[Any, ...]) -> None:
        self._rows.append(row)
        self.count += 1
        if len(self._rows) >= INSERT_BATCH_SIZE:
            self.flush()

    def flush(self) -> None:
        if self._rows:
            self._connection.executemany(self._statement, self._rows)
            self._rows.clear()


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------


def build_index(
    sources: ResolvedSources,
    destination: Path,
    *,
    progress: ProgressSink | None = None,
    cancel: Event | None = None,
    cifp_idents: frozenset[str] = frozenset(),
) -> BuildStats | None:
    """Write a complete index to ``destination``.

    Args:
        sources: The resolved source files.
        destination: A temporary path. The caller publishes it.
        progress: Throttled progress frames.
        cancel: Checked per insert batch and per progress emission.
        cifp_idents: Airports that have a CIFP file, from **one directory
            listing** rather than a ``stat()`` per airport. It only sets
            ``has_procedures``, which lets the UI grey out the procedure tabs
            before any lazy parse happens.

    Returns:
        The build statistics, or ``None`` when the build was cancelled. A
        cancelled build has written nothing anybody can see.

    Raises:
        NavdataIndexError: The build itself failed — I/O error, disk full,
            unreadable source. A malformed *record* never raises: it is skipped
            and counted.
    """
    started = time.monotonic()
    pump = _Progress(progress)
    skipped = _SkipCounter()
    connection = _connect_for_build(destination)

    try:
        prepare_for_build(connection)
        apply_schema(connection)

        counts = _index_all_sources(connection, sources, pump, cancel, skipped, cifp_idents)
        if counts is None:
            return None
        airports, runways, parking, navaids, fixes, holds = counts

        stats = BuildStats(
            airport_count=airports,
            runway_count=runways,
            parking_count=parking,
            navaid_count=navaids,
            fix_count=fixes,
            hold_count=holds,
            skipped_record_count=skipped.total,
            duration_s=time.monotonic() - started,
        )
        _finalise_build(connection, sources, stats, pump)
    except sqlite3.Error as error:
        raise NavdataIndexError(f"The navdata index build failed: {error}") from error
    except OSError as error:
        raise NavdataIndexError(f"Could not read the navdata source files: {error}") from error
    finally:
        connection.close()

    return stats


def _connect_for_build(destination: Path) -> sqlite3.Connection:
    """Open (or create) the sqlite file at ``destination`` for a fresh build.

    Raises:
        NavdataIndexError: disk-level failure.
    """
    try:
        return sqlite3.connect(destination)
    except sqlite3.Error as error:  # pragma: no cover - disk-level failure
        raise NavdataIndexError(
            f"Could not create the navdata index at {destination}: {error}"
        ) from error


def _index_all_sources(
    connection: sqlite3.Connection,
    sources: ResolvedSources,
    pump: _Progress,
    cancel: Event | None,
    skipped: _SkipCounter,
    cifp_idents: frozenset[str],
) -> tuple[int, int, int, int, int, int] | None:
    """Run every indexing pass in turn, stopping early if cancelled.

    Returns:
        ``(airports, runways, parking, navaids, fixes, holds)`` counts, or
        ``None`` when the build was cancelled partway through.
    """
    counts = _index_airports(connection, sources, pump, cancel, skipped, cifp_idents)
    if counts is None:
        return None
    airports, runways, parking = counts

    navaids = _index_navaids(connection, sources, pump, cancel, skipped)
    if navaids is None:
        return None

    fixes = _index_fixes(connection, sources, pump, cancel, skipped)
    if fixes is None:
        return None

    holds = _index_holds(connection, sources, pump, cancel, skipped)
    if holds is None:
        return None

    return airports, runways, parking, navaids, fixes, holds


def _finalise_build(
    connection: sqlite3.Connection,
    sources: ResolvedSources,
    stats: BuildStats,
    pump: _Progress,
) -> None:
    """Write metadata, commit and apply the finalise pragmas."""
    pump.enter("finalising")
    _write_metadata(connection, sources, stats)
    connection.commit()
    for statement in FINALISE_PRAGMAS:
        connection.execute(statement)
    pump.update(1.0, "index written")


class _SkipCounter:
    """Counts malformed records. One bad row never fails a build (§4.6)."""

    def __init__(self) -> None:
        self.total = 0
        self.first_reason: str | None = None

    def __call__(self, reason: str, line: str) -> None:
        del line
        self.total += 1
        if self.first_reason is None:
            self.first_reason = reason


def _index_airports(
    connection: sqlite3.Connection,
    sources: ResolvedSources,
    pump: _Progress,
    cancel: Event | None,
    skipped: _SkipCounter,
    cifp_idents: frozenset[str],
) -> tuple[int, int, int] | None:
    """The single pass over ``apt.dat`` — airports, runways and parking together.

    One pass, because the file is 380 MB and reading it three times would triple
    the only part of the build the user actually waits for.
    """
    path = sources.path("apt")
    if path is None:
        return 0, 0, 0

    airports = _Batch(connection, INSERT_AIRPORT)
    runways = _Batch(connection, INSERT_RUNWAY)
    parking = _Batch(connection, INSERT_PARKING)
    size = max(_size_of(path), 1)

    pump.enter("airports")
    with path.open(encoding="utf-8", errors="replace") as handle:
        for index, airport in enumerate(iter_airports(handle, on_skip=skipped), start=1):
            _add_airport(airports, runways, parking, airport, cifp_idents)

            # Ticked per airport, not per line: 31 000 checks instead of
            # 12 350 000, and the per-line loop stays a bare startswith().
            if index % 256 == 0:
                if _cancelled(cancel):
                    return None
                pump.update(
                    _position(handle) / size,
                    f"apt.dat - {index:,} airports",
                )

    airports.flush()
    pump.enter("runways")
    runways.flush()
    pump.enter("parking")
    parking.flush()
    connection.commit()
    return airports.count, runways.count, parking.count


def _add_airport(
    airports: _Batch,
    runways: _Batch,
    parking: _Batch,
    airport: ParsedAirport,
    cifp_idents: frozenset[str],
) -> None:
    latitude = airport.latitude
    longitude = airport.longitude
    if latitude is None or longitude is None:  # pragma: no cover - _finalise guarantees this
        return

    airports.add(
        (
            airport.icao,
            airport.iata,
            airport.name,
            normalize_search_text(airport.name),
            airport.city,
            airport.country,
            airport.region_code,
            latitude,
            longitude,
            airport.elevation_ft,
            airport.transition_altitude_ft,
            airport.transition_level_ft,
            airport.magnetic_variation_deg,
            int(airport.has_tower),
            airport.runway_count,
            airport.longest_runway_m,
            int(airport.icao in cifp_idents),
        )
    )

    for runway in airport.runways:
        runways.add(
            (
                airport.icao,
                runway.ident,
                runway.opposite_ident,
                runway.threshold_lat,
                runway.threshold_lon,
                runway.end_lat,
                runway.end_lon,
                runway.true_bearing_deg,
                runway.length_m,
                runway.displaced_threshold_m,
                runway.width_m,
                runway.surface,
                airport.elevation_ft,
            )
        )

    for stand in airport.parking:
        parking.add(
            (
                airport.icao,
                stand.name,
                stand.latitude,
                stand.longitude,
                stand.heading_true_deg,
                stand.kind,
                stand.aircraft_types,
                stand.operation,
                stand.airline_codes,
            )
        )


def _index_navaids(
    connection: sqlite3.Connection,
    sources: ResolvedSources,
    pump: _Progress,
    cancel: Event | None,
    skipped: _SkipCounter,
) -> int | None:
    path = sources.path("earth_nav")
    if path is None:
        return 0

    batch = _Batch(connection, INSERT_NAVAID)
    size = max(_size_of(path), 1)
    pump.enter("navaids")

    with path.open(encoding="utf-8", errors="replace") as handle:
        for index, navaid in enumerate(parse_earth_nav(handle, on_skip=skipped), start=1):
            batch.add(
                (
                    navaid.ident,
                    navaid.kind,
                    navaid.name,
                    navaid.latitude,
                    navaid.longitude,
                    navaid.elevation_ft,
                    navaid.frequency_khz,
                    navaid.channel,
                    navaid.range_nm,
                    navaid.true_deg,
                    navaid.mag_deg,
                    navaid.glideslope_deg,
                    navaid.magnetic_variation_deg,
                    navaid.region_code,
                    navaid.airport_icao,
                    navaid.runway_ident,
                    None,
                )
            )
            if index % INSERT_BATCH_SIZE == 0:
                if _cancelled(cancel):
                    return None
                pump.update(_position(handle) / size, f"earth_nav.dat - {index:,} navaids")

    batch.flush()
    connection.commit()
    return batch.count


def _index_fixes(
    connection: sqlite3.Connection,
    sources: ResolvedSources,
    pump: _Progress,
    cancel: Event | None,
    skipped: _SkipCounter,
) -> int | None:
    path = sources.path("earth_fix")
    if path is None:
        return 0

    batch = _Batch(connection, INSERT_FIX)
    size = max(_size_of(path), 1)
    pump.enter("fixes")

    with path.open(encoding="utf-8", errors="replace") as handle:
        for index, fix in enumerate(parse_earth_fix(handle, on_skip=skipped), start=1):
            batch.add(
                (
                    fix.ident,
                    fix.latitude,
                    fix.longitude,
                    fix.region_code,
                    fix.terminal_airport_icao,
                    fix.name,
                )
            )
            if index % INSERT_BATCH_SIZE == 0:
                if _cancelled(cancel):
                    return None
                pump.update(_position(handle) / size, f"earth_fix.dat - {index:,} fixes")

    batch.flush()
    connection.commit()
    return batch.count


def _index_holds(
    connection: sqlite3.Connection,
    sources: ResolvedSources,
    pump: _Progress,
    cancel: Event | None,
    skipped: _SkipCounter,
) -> int | None:
    path = sources.path("earth_hold")
    pump.enter("holds")
    if path is None:
        # earth_hold.dat is optional: an install without it simply publishes no
        # holds, which the whole stack already handles as an ordinary case.
        return 0

    batch = _Batch(connection, INSERT_HOLD)
    size = max(_size_of(path), 1)

    with path.open(encoding="utf-8", errors="replace") as handle:
        for index, hold in enumerate(parse_earth_hold(handle, on_skip=skipped), start=1):
            batch.add(
                (
                    hold.fix_ident,
                    hold.region_code,
                    hold.airport_icao,
                    hold.fix_type,
                    hold.inbound_course_mag_deg,
                    hold.leg_time_min,
                    hold.leg_length_nm,
                    hold.turn_direction,
                    hold.min_altitude_ft,
                    hold.max_altitude_ft,
                    hold.speed_kt,
                )
            )
            if index % INSERT_BATCH_SIZE == 0:
                if _cancelled(cancel):
                    return None
                pump.update(_position(handle) / size, f"earth_hold.dat - {index:,} holds")

    batch.flush()
    connection.commit()
    return batch.count


def _write_metadata(
    connection: sqlite3.Connection, sources: ResolvedSources, stats: BuildStats
) -> None:
    cycle = sources.cycle
    rows: list[tuple[str, str]] = [
        ("schema_version", str(SCHEMA_VERSION)),
        ("cache_key", sources.cache_key),
        ("source_root", str(sources.root)),
        ("built_at", datetime.now(tz=UTC).isoformat()),
        ("build_duration_s", f"{stats.duration_s:.3f}"),
        ("skipped_record_count", str(stats.skipped_record_count)),
        ("airport_count", str(stats.airport_count)),
        ("runway_count", str(stats.runway_count)),
        ("parking_count", str(stats.parking_count)),
        ("navaid_count", str(stats.navaid_count)),
        ("fix_count", str(stats.fix_count)),
        ("hold_count", str(stats.hold_count)),
    ]
    if cycle is not None:
        rows.append(("airac_cycle", cycle.cycle))
        if cycle.valid_from is not None:
            rows.append(("cycle_valid_from", cycle.valid_from.isoformat()))
        if cycle.valid_to is not None:
            rows.append(("cycle_valid_to", cycle.valid_to.isoformat()))

    connection.executemany(INSERT_META, rows)
    connection.executemany(
        INSERT_SOURCE_FILE,
        [(f.role, str(f.path), f.size_bytes, f.mtime_ns) for f in sources.files],
    )


def _cancelled(cancel: Event | None) -> bool:
    return cancel is not None and cancel.is_set()


def _position(handle: Any) -> int:
    """Byte offset into the source, for the progress fraction.

    Read off the *buffered* reader, which runs ahead of the decoded position.
    That is fine for a progress bar and is O(1); ``TextIOWrapper.tell()`` is
    neither.
    """
    try:
        position = handle.buffer.tell()
    except (AttributeError, OSError):
        return 0
    return int(position)


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
