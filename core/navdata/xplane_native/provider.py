"""The indexed :class:`~core.navdata.provider.NavdataProvider` over an X-Plane data tree.

``earth_*.dat`` and ``apt.dat`` are indexed into SQLite up front and every query
here is a plain statement against that index. ``CIFP/<ICAO>.dat`` is **not**:
there are ~15 000 of them, an instructor session touches perhaps five, and
parsing them all at start-up would burn minutes to produce data that is 99.97%
unused. Procedures therefore arrive through an injected
:class:`~core.navdata.cifp_source.CifpSource`, which defaults to
:class:`~core.navdata.cifp_source.NullCifpSource` — every airport reads as
having no procedures, which the whole stack already handles as an ordinary case.

Three rules govern the runtime shape of this class, and each of them exists to
prevent a failure that only appears under load or only on Windows:

**Status is published by whole-object assignment.** The build thread never
mutates a shared status; it constructs a whole new frozen
:class:`~core.navdata.models.NavdataStatus` and assigns one attribute.
:meth:`status` does nothing but return that reference. Both operations are
individually atomic under the GIL, so a reader sees the status before the update
or the one after — never a torn mix of ``state="ready"`` beside a progress bar
at 62%. That is the *only* synchronisation this class needs: no lock, no queue.

**Read connections are thread-local and carry their epoch.** ``sqlite3``
connections must not cross threads, and FastAPI runs synchronous routes in a
threadpool. Each connection records the generation epoch it was opened at and is
reopened when the provider's epoch has moved on, so a rebuild is picked up
without recreating the provider and without a query in flight ever seeing the
file change underneath it.

**Spatial queries prefilter with a bounding box and refine geodesically.** No
R\\*Tree: it is an optional SQLite compile-time module, and depending on it means
depending on how CPython was built on four CI targets and on whatever Python the
PyInstaller bundle ships. A 50 NM box holds a few hundred rows, so the exact
refine in Python is trivial.
"""

from __future__ import annotations

import math
import os
import sqlite3
import threading
from collections.abc import Callable, Collection, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from core.geodesy import distance_and_bearing
from core.models import GeoPosition, Ils, Runway, RunwaySurface
from core.navdata.cifp_source import CifpRunway, CifpSource, NullCifpSource
from core.navdata.models import (
    Airport,
    AirportSummary,
    Fix,
    FixRef,
    Hold,
    IndexProgress,
    Navaid,
    NavaidKind,
    NavdataStatus,
    ParkingKind,
    ParkingOperation,
    ParkingStand,
    Procedure,
    ProcedureKind,
    ProcedureSummary,
    Waypoint,
    WaypointKind,
)
from core.navdata.normalize import normalize_icao, normalize_runway_ident, normalize_search_text
from core.navdata.provider import NavdataUnavailable
from core.navdata.sources import discover_xplane_root, is_valid_xplane_root
from core.navdata.xplane_native.build import (
    BuildLockTimeout,
    ResolvedSources,
    advisory_lock,
    build_index,
    cache_directory,
    generation_files,
    next_generation_path,
    read_cache_key,
    read_only_uri,
    resolve_sources,
    sweep_generations,
)
from core.navdata.xplane_native.earth import tunable_radio_for

__all__ = ["PROVIDER_NAME", "XPNativeNavdataProvider"]

PROVIDER_NAME = "xplane_native"

#: Navaid kinds a 4-part ARINC ``D`` reference (VHF navaid) may resolve to.
_VHF_KINDS: tuple[NavaidKind, ...] = ("vor", "vor_dme", "vortac", "dme", "tacan")

#: Named, so the ``Literal`` survives into the call. An inline ``("ndb",)`` is
#: inferred as ``tuple[str]`` and does not type-check.
_NDB_KINDS: tuple[NavaidKind, ...] = ("ndb",)
_LOCALIZER_KINDS: tuple[NavaidKind, ...] = ("localizer",)

_NAVAID_WAYPOINT_KIND: dict[str, WaypointKind] = {
    "vor": "vor",
    "vor_dme": "vor",
    "vortac": "vor",
    "dme": "dme",
    "tacan": "tacan",
    "ndb": "ndb",
    "localizer": "localizer",
    "glideslope": "localizer",
    "gls": "gls",
}

_SURFACES: frozenset[str] = frozenset(
    {
        "asphalt",
        "concrete",
        "grass",
        "dirt",
        "gravel",
        "dry_lakebed",
        "water",
        "snow",
        "transparent",
        "unknown",
    }
)

_PARKING_KINDS: frozenset[str] = frozenset({"gate", "hangar", "tie_down", "misc"})
_PARKING_OPERATIONS: frozenset[str] = frozenset(
    {"none", "general_aviation", "airline", "cargo", "military"}
)

#: Latitude beyond which the longitude half-width of a bounding box stops being
#: meaningful. Above it the latitude band alone prefilters.
_POLAR_LATITUDE_DEG = 85.0

_AIRPORT_COLUMNS = (
    "icao, iata, name, city, country, region_code, latitude, longitude, elevation_ft, "
    "transition_altitude_ft, transition_level_ft, magnetic_variation_deg, has_tower, "
    "runway_count, longest_runway_m, has_procedures"
)

_SUMMARY_COLUMNS = (
    "icao, iata, name, latitude, longitude, elevation_ft, longest_runway_m, has_procedures"
)

_RUNWAY_QUERY = """
SELECT r.airport_icao, r.ident, r.opposite_ident,
       r.threshold_lat, r.threshold_lon, r.end_lat, r.end_lon,
       r.true_bearing_deg, r.length_m, r.displaced_threshold_m,
       r.width_m, r.surface, r.elevation_ft,
       n.ident AS loc_ident, n.frequency_khz AS loc_freq_khz,
       n.true_deg AS loc_true_deg, n.mag_deg AS loc_mag_deg,
       n.latitude AS loc_lat, n.longitude AS loc_lon, n.elevation_ft AS loc_elev_ft,
       g.glideslope_deg AS gs_deg, g.latitude AS gs_lat, g.longitude AS gs_lon,
       g.elevation_ft AS gs_elev_ft,
       d.id AS dme_id
FROM runway r
LEFT JOIN navaid n ON n.airport_icao = r.airport_icao
                  AND n.runway_ident = r.ident AND n.kind = 'localizer'
LEFT JOIN navaid g ON g.airport_icao = r.airport_icao
                  AND g.runway_ident = r.ident AND g.kind = 'glideslope'
LEFT JOIN navaid d ON d.airport_icao = r.airport_icao
                  AND d.runway_ident = r.ident AND d.kind IN ('dme', 'tacan')
WHERE r.airport_icao = ?
ORDER BY r.ident
"""

_SEARCH_QUERY = f"""
SELECT {_SUMMARY_COLUMNS},
       CASE
           WHEN icao        =  :upper           THEN 0
           WHEN icao   LIKE :upper || '%'       THEN 1
           WHEN iata        =  :upper           THEN 2
           WHEN name_norm LIKE :norm || '%'     THEN 3
           ELSE 4
       END AS rank
FROM airport
WHERE icao LIKE :upper || '%'
   OR iata = :upper
   OR name_norm LIKE '%' || :norm || '%'
ORDER BY rank, longest_runway_m IS NULL, longest_runway_m DESC, icao
LIMIT :limit
"""


class _ReadState(threading.local):
    """One SQLite connection per thread, tagged with the generation it opened."""

    connection: sqlite3.Connection | None = None
    epoch: int = -1


class XPNativeNavdataProvider:
    """Serve navdata from a user's X-Plane data tree via an on-disk SQLite index."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        cache_dir: Path | None = None,
        cifp_source: CifpSource | None = None,
    ) -> None:
        """Construct the provider. **This performs no I/O.**

        Args:
            root: The X-Plane installation. ``None`` means autodetect, which
                happens on the first :meth:`ensure_index` call rather than here.
            cache_dir: Where the index file lives. ``None`` means the platform
                user-cache directory — never the repository and never inside the
                X-Plane install, which may be read-only or on a network drive.
            cifp_source: Where procedures come from. Defaults to
                :class:`~core.navdata.cifp_source.NullCifpSource`, i.e. no
                procedures anywhere, which is a correct answer for an airport
                without a CIFP file and a degraded one otherwise — never a
                crash.
        """
        self._configured_root = root
        self._cache_dir_override = cache_dir
        self._cifp: CifpSource = cifp_source if cifp_source is not None else NullCifpSource()

        self._status = NavdataStatus(
            state="unavailable",
            reason="The navigation index has not been built yet.",
            provider=PROVIDER_NAME,
        )
        self._path: Path | None = None
        self._epoch = 0
        self._read = _ReadState()
        self._build_mutex = threading.Lock()

    # --- Identity and lifecycle -------------------------------------------

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def cache_path(self) -> Path | None:
        """The generation currently published, or ``None``. Diagnostics and tests."""
        return self._path

    def status(self) -> NavdataStatus:
        """Return the published snapshot. One attribute read; never raises."""
        return self._status

    def close(self) -> None:
        """Release **this thread's** read connection.

        Not part of the protocol — a provider is a process-lifetime singleton
        and normally never closed. It exists because Windows refuses to delete a
        file that still has an open handle, so a test using a temporary cache
        directory has to be able to let go of it.
        """
        state = self._read
        if state.connection is not None:
            state.connection.close()
            state.connection = None
            state.epoch = -1

    def ensure_index(
        self,
        *,
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
        force: bool = False,
    ) -> NavdataStatus:
        with self._build_mutex:
            return self._ensure_index(progress=progress, cancel=cancel, force=force)

    # --- Airports ----------------------------------------------------------

    def get_airport(self, icao: str) -> Airport | None:
        row = self._query_one(
            f"SELECT {_AIRPORT_COLUMNS} FROM airport WHERE icao = ?", (normalize_icao(icao),)
        )
        return _airport(row) if row is not None else None

    def search_airports(self, query: str, *, limit: int = 20) -> list[AirportSummary]:
        needle = normalize_search_text(query)
        if not needle:
            return []
        rows = self._query(
            _SEARCH_QUERY, {"upper": needle.upper(), "norm": needle, "limit": max(limit, 0)}
        )
        return [_summary(row) for row in rows]

    def airports_near(
        self, centre: GeoPosition, radius_nm: float, *, limit: int = 50
    ) -> list[AirportSummary]:
        rows = self._near(f"SELECT {_SUMMARY_COLUMNS} FROM airport", centre, radius_nm, limit)
        return [_summary(row) for row in rows]

    # --- Runways -----------------------------------------------------------

    def get_runways(self, icao: str) -> list[Runway]:
        """Every runway end of an airport, merged from ``apt.dat`` and the CIFP.

        The CIFP load is triggered **on every call**, deliberately. Runway data
        is a merge of two sources, and returning a different ``threshold`` or
        ``elevation_ft`` depending on whether that airport's CIFP file happened
        to be warm would be the worst possible bug in this whole module.
        """
        wanted = normalize_icao(icao)
        rows = self._query(_RUNWAY_QUERY, (wanted,))
        if not rows:
            return []

        cifp = self._cifp.load(wanted)
        return [_runway(row, cifp.runway(_text(row, "ident")) if cifp else None) for row in rows]

    def get_runway(self, icao: str, ident: str) -> Runway | None:
        wanted = normalize_runway_ident(ident)
        return next((r for r in self.get_runways(icao) if r.ident == wanted), None)

    # --- Parking -----------------------------------------------------------

    def get_parking(self, icao: str, *, kind: ParkingKind | None = None) -> list[ParkingStand]:
        sql = (
            "SELECT airport_icao, name, latitude, longitude, heading_true_deg, kind, "
            "aircraft_types, operation, airline_codes FROM parking WHERE airport_icao = ?"
        )
        parameters: list[Any] = [normalize_icao(icao)]
        if kind is not None:
            sql += " AND kind = ?"
            parameters.append(kind)
        return [_parking(row) for row in self._query(f"{sql} ORDER BY name", tuple(parameters))]

    # --- Procedures --------------------------------------------------------

    def get_procedures(
        self, icao: str, *, kind: ProcedureKind | None = None
    ) -> list[ProcedureSummary]:
        procedures = self._procedures(icao)
        if kind is not None:
            procedures = [p for p in procedures if p.kind == kind]
        return [_procedure_summary(p) for p in sorted(procedures, key=_procedure_sort_key)]

    def get_procedure(
        self,
        icao: str,
        kind: ProcedureKind,
        ident: str,
        transition: str | None = None,
    ) -> Procedure | None:
        return next(
            (
                p
                for p in self._procedures(icao)
                if p.kind == kind and p.ident == ident and p.transition == transition
            ),
            None,
        )

    def _procedures(self, icao: str) -> list[Procedure]:
        airport = self._cifp.load(normalize_icao(icao))
        return list(airport.procedures) if airport is not None else []

    # --- Navaids and fixes -------------------------------------------------

    def get_navaids(
        self,
        ident: str,
        *,
        region: str | None = None,
        kinds: Collection[NavaidKind] | None = None,
    ) -> list[Navaid]:
        sql = f"SELECT {_NAVAID_COLUMNS} FROM navaid WHERE ident = ?"
        parameters: list[Any] = [ident.strip().upper()]
        if region is not None:
            sql += " AND region_code = ?"
            parameters.append(region)
        sql += _kind_filter(kinds, parameters)
        sql += " ORDER BY ident, region_code IS NULL, region_code, id"
        return [_navaid(row) for row in self._query(sql, tuple(parameters))]

    def navaids_near(
        self,
        centre: GeoPosition,
        radius_nm: float,
        *,
        kinds: Collection[NavaidKind] | None = None,
        limit: int = 50,
    ) -> list[Navaid]:
        extra: list[Any] = []
        clause = _kind_filter(kinds, extra)
        rows = self._near(
            f"SELECT {_NAVAID_COLUMNS} FROM navaid",
            centre,
            radius_nm,
            limit,
            extra_clause=clause,
            extra_parameters=extra,
        )
        return [_navaid(row) for row in rows]

    def get_ils(self, icao: str, runway_ident: str) -> Ils | None:
        runway = self.get_runway(icao, runway_ident)
        return runway.ils if runway is not None else None

    def get_fixes(
        self,
        ident: str,
        *,
        region: str | None = None,
        terminal_airport: str | None = None,
    ) -> list[Fix]:
        sql = f"SELECT {_FIX_COLUMNS} FROM fix WHERE ident = ?"
        parameters: list[Any] = [ident.strip().upper()]
        if region is not None:
            sql += " AND region_code = ?"
            parameters.append(region)
        if terminal_airport is not None:
            sql += " AND terminal_airport_icao = ?"
            parameters.append(normalize_icao(terminal_airport))
        sql += " ORDER BY ident, region_code IS NULL, region_code, id"
        return [_fix(row) for row in self._query(sql, tuple(parameters))]

    def fixes_near(self, centre: GeoPosition, radius_nm: float, *, limit: int = 50) -> list[Fix]:
        rows = self._near(f"SELECT {_FIX_COLUMNS} FROM fix", centre, radius_nm, limit)
        return [_fix(row) for row in rows]

    def resolve_fix(self, ref: FixRef) -> Waypoint | None:
        """Turn a 4-part ARINC key into a coordinate — the single place that mapping lives.

        The section/subsection pair says which table to look in. Getting it
        wrong is not a small error: collapsing the terminal scope of ``P``/``C``
        would make roughly half the legs of a typical SID unresolvable.
        """
        section = ref.section.strip().upper()
        subsection = ref.subsection.strip().upper()

        if section == "D":
            kinds = _NDB_KINDS if subsection == "B" else _VHF_KINDS
            return _navaid_waypoint(
                self.get_navaids(ref.ident, region=ref.region_code, kinds=kinds)
            )

        if section == "E":
            enroute = [
                f
                for f in self.get_fixes(ref.ident, region=ref.region_code)
                if f.terminal_airport_icao is None
            ]
            return _fix_waypoint(enroute[0]) if enroute else None

        if section == "P":
            return self._resolve_terminal(ref, subsection)

        return None

    # --- Holds -------------------------------------------------------------

    def get_holds(
        self,
        *,
        fix_ident: str | None = None,
        region: str | None = None,
        airport_icao: str | None = None,
    ) -> list[Hold]:
        sql = (
            "SELECT fix_ident, region_code, airport_icao, fix_type, inbound_course_mag_deg, "
            "leg_time_min, leg_length_nm, turn_direction, min_altitude_ft, max_altitude_ft, "
            "speed_kt FROM hold WHERE 1 = 1"
        )
        parameters: list[Any] = []
        if fix_ident is not None:
            sql += " AND fix_ident = ?"
            parameters.append(fix_ident.strip().upper())
        if region is not None:
            sql += " AND region_code = ?"
            parameters.append(region)
        if airport_icao is not None:
            sql += " AND airport_icao = ?"
            parameters.append(normalize_icao(airport_icao))

        holds: list[Hold] = []
        for row in self._query(f"{sql} ORDER BY fix_ident, id", tuple(parameters)):
            hold = self._hold(row)
            if hold is not None:
                holds.append(hold)
        return holds

    # --- Index lifecycle ---------------------------------------------------

    def _ensure_index(
        self,
        *,
        progress: Callable[[IndexProgress], None] | None,
        cancel: threading.Event | None,
        force: bool,
    ) -> NavdataStatus:
        previous = self._status

        root = self._resolve_root()
        if root is None:
            return self._publish_unavailable(
                "No X-Plane 12 installation found. Set OIS_XPLANE_PATH or choose your "
                "X-Plane folder."
            )

        sources = resolve_sources(root)
        if sources.missing_roles:
            return self._publish_unavailable(
                f"The X-Plane installation at {root} is missing "
                f"{', '.join(f'{role}.dat' for role in sources.missing_roles)}."
            )

        if not force:
            adopted = self._adopt(sources)
            if adopted is not None:
                return adopted

        if cancel is not None and cancel.is_set():
            self._status = previous
            return previous

        cache_dir = self._cache_dir()
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            with advisory_lock(cache_dir / "build.lock"):
                if not force:
                    # The winner has usually just published; adopt its work
                    # rather than repeating two minutes of it.
                    adopted = self._adopt(sources)
                    if adopted is not None:
                        return adopted
                return self._build(sources, progress, cancel, previous)
        except BuildLockTimeout as error:
            return self._publish_error(str(error))
        except OSError as error:
            return self._publish_error(f"The navdata cache directory is unusable: {error}")

    def _build(
        self,
        sources: ResolvedSources,
        progress: Callable[[IndexProgress], None] | None,
        cancel: threading.Event | None,
        previous: NavdataStatus,
    ) -> NavdataStatus:
        cache_dir = self._cache_dir()
        building = NavdataStatus(
            state="building",
            reason="Indexing your X-Plane navigation data.",
            provider=PROVIDER_NAME,
            source_root=str(sources.root),
            airac_cycle=sources.cycle.cycle if sources.cycle is not None else None,
        )
        self._status = building

        def sink(frame: IndexProgress) -> None:
            # Whole-object assignment: a reader never sees "ready" beside a
            # half-finished progress bar.
            self._status = building.model_copy(update={"progress": frame})
            if progress is not None:
                progress(frame)

        temporary = cache_dir / f"navdata-build-{os.getpid()}.tmp"
        temporary.unlink(missing_ok=True)

        try:
            stats = build_index(
                sources,
                temporary,
                progress=sink,
                cancel=cancel,
                cifp_idents=_cifp_idents(sources.root),
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            self._status = self._error_status(
                sources, "The navigation index build failed. See the log for details."
            )
            raise

        if stats is None:
            # Cancelled. Nothing is published and the previous index — if there
            # was one — is still exactly where it was.
            temporary.unlink(missing_ok=True)
            self._status = previous
            return previous

        cycle = sources.cycle.cycle if sources.cycle is not None else None
        target = next_generation_path(cache_dir, cycle)
        temporary.replace(target)

        published = self._publish(target, sources)
        sweep_generations(cache_dir, keep=target)
        return published

    def _adopt(self, sources: ResolvedSources) -> NavdataStatus | None:
        """Take over a published generation whose cache key still matches."""
        key = sources.cache_key
        for _, path in reversed(generation_files(self._cache_dir())):
            if read_cache_key(path) == key:
                return self._publish(path, sources)
        return None

    def _publish(self, path: Path, sources: ResolvedSources) -> NavdataStatus:
        """Point readers at a new generation and bump the epoch.

        The path is assigned **before** the epoch: a reader that observes the
        new epoch is guaranteed to find the new path already in place, and one
        that observes the old epoch keeps its perfectly good connection.
        """
        meta = _read_meta(path)
        self._path = path
        self._epoch += 1
        self._cifp.invalidate()

        self._status = NavdataStatus(
            state="ready",
            reason=None,
            provider=PROVIDER_NAME,
            source_root=str(sources.root),
            airac_cycle=meta.get("airac_cycle"),
            cycle_valid_from=_as_date(meta.get("cycle_valid_from")),
            cycle_valid_to=_as_date(meta.get("cycle_valid_to")),
            built_at=_as_datetime(meta.get("built_at")),
            airport_count=_as_int(meta.get("airport_count")),
            runway_count=_as_int(meta.get("runway_count")),
            navaid_count=_as_int(meta.get("navaid_count")),
            fix_count=_as_int(meta.get("fix_count")),
        )
        return self._status

    def _publish_unavailable(self, reason: str) -> NavdataStatus:
        self._status = NavdataStatus(state="unavailable", reason=reason, provider=PROVIDER_NAME)
        return self._status

    def _publish_error(self, reason: str) -> NavdataStatus:
        self._status = NavdataStatus(state="error", reason=reason, provider=PROVIDER_NAME)
        return self._status

    def _error_status(self, sources: ResolvedSources, reason: str) -> NavdataStatus:
        return NavdataStatus(
            state="error",
            reason=reason,
            provider=PROVIDER_NAME,
            source_root=str(sources.root),
        )

    def _resolve_root(self) -> Path | None:
        if self._configured_root is not None:
            return self._configured_root if is_valid_xplane_root(self._configured_root) else None
        return discover_xplane_root()

    def _cache_dir(self) -> Path:
        return cache_directory(self._cache_dir_override)

    # --- Reading -----------------------------------------------------------

    def _connection(self) -> sqlite3.Connection:
        path = self._path
        epoch = self._epoch
        if path is None:
            raise NavdataUnavailable(PROVIDER_NAME, self._status.reason or "No index is published.")

        state = self._read
        if state.connection is not None and state.epoch == epoch:
            return state.connection

        if state.connection is not None:
            state.connection.close()
            state.connection = None

        connection = sqlite3.connect(read_only_uri(path), uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = 1")
        state.connection = connection
        state.epoch = epoch
        return connection

    def _query(self, sql: str, parameters: Any = ()) -> list[sqlite3.Row]:
        return list(self._connection().execute(sql, parameters).fetchall())

    def _query_one(self, sql: str, parameters: Any = ()) -> sqlite3.Row | None:
        row = self._connection().execute(sql, parameters).fetchone()
        return cast("sqlite3.Row | None", row)

    def _near(
        self,
        select: str,
        centre: GeoPosition,
        radius_nm: float,
        limit: int,
        *,
        extra_clause: str = "",
        extra_parameters: Sequence[Any] = (),
    ) -> list[sqlite3.Row]:
        """Bounding-box prefilter on the indexed coordinate, then an exact refine.

        The box is generous by construction — it is a rectangle around a circle —
        so it never drops a row the geodesic would have kept, and the refine
        never has to trust it.
        """
        if radius_nm <= 0.0:
            return []

        seen: dict[int, tuple[float, sqlite3.Row]] = {}
        for lat_min, lat_max, lon_min, lon_max in _bounding_boxes(centre, radius_nm):
            sql = (
                f"{select} WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?"
                f"{extra_clause}"
            )
            parameters = [lat_min, lat_max, lon_min, lon_max, *extra_parameters]
            for row in self._query(sql, tuple(parameters)):
                distance_nm, _ = distance_and_bearing(
                    centre,
                    GeoPosition(
                        latitude=_float(row, "latitude"),
                        longitude=_float(row, "longitude"),
                        altitude_ft=0.0,
                    ),
                )
                if distance_nm <= radius_nm:
                    seen[id(row)] = (distance_nm, row)

        ordered = sorted(seen.values(), key=lambda item: item[0])
        return [row for _, row in ordered[: max(limit, 0)]]

    # --- Resolution helpers ------------------------------------------------

    def _resolve_terminal(self, ref: FixRef, subsection: str) -> Waypoint | None:
        """The ``P`` section: everything scoped to one airport."""
        airport_icao = ref.airport_icao

        if subsection == "A":
            airport = self.get_airport(ref.ident)
            if airport is None:
                return None
            return Waypoint(
                ident=airport.icao,
                kind="airport",
                position=airport.position,
                region_code=airport.region_code,
                name=airport.name,
            )

        if subsection == "G":
            if airport_icao is None:
                return None
            runway = self.get_runway(airport_icao, ref.ident)
            if runway is None:
                return None
            return Waypoint(
                ident=runway.ident,
                kind="runway",
                position=runway.threshold,
                airport_icao=runway.airport_icao,
            )

        if subsection in {"I", "N"}:
            kinds = _LOCALIZER_KINDS if subsection == "I" else _NDB_KINDS
            candidates = [
                n
                for n in self.get_navaids(ref.ident, region=ref.region_code, kinds=kinds)
                if airport_icao is None or n.airport_icao in (None, normalize_icao(airport_icao))
            ]
            return _navaid_waypoint(candidates)

        if airport_icao is None:
            return None
        terminal = self.get_fixes(ref.ident, region=ref.region_code, terminal_airport=airport_icao)
        return _fix_waypoint(terminal[0]) if terminal else None

    def _hold(self, row: sqlite3.Row) -> Hold | None:
        """Attach a coordinate to a published hold.

        ``earth_hold.dat`` names its fix but does not position it, so the hold
        is joined to the fix or navaid tables through the shared fix-type enum
        (11 waypoint, 3 VOR, 2 NDB). A hold whose fix is not in the index is
        **dropped**: it cannot be drawn, entered or flown, and returning it
        without a position would push the same decision onto every consumer.
        """
        fix = self._hold_waypoint(row)
        if fix is None:
            return None
        return Hold(
            fix=fix,
            inbound_course_mag_deg=_float(row, "inbound_course_mag_deg"),
            turn_direction=cast("Any", _text(row, "turn_direction")),
            leg_time_min=_optional_float(row, "leg_time_min"),
            leg_length_nm=_optional_float(row, "leg_length_nm"),
            min_altitude_ft=_optional_float(row, "min_altitude_ft"),
            max_altitude_ft=_optional_float(row, "max_altitude_ft"),
            speed_kt=_optional_float(row, "speed_kt"),
            airport_icao=_optional_text(row, "airport_icao"),
        )

    def _hold_waypoint(self, row: sqlite3.Row) -> Waypoint | None:
        ident = _text(row, "fix_ident")
        region = _optional_text(row, "region_code")
        airport = _optional_text(row, "airport_icao")
        fix_type = _optional_int(row, "fix_type")

        if fix_type == 3:
            return _navaid_waypoint(self.get_navaids(ident, region=region, kinds=_VHF_KINDS))
        if fix_type == 2:
            return _navaid_waypoint(self.get_navaids(ident, region=region, kinds=_NDB_KINDS))

        fixes = self.get_fixes(ident, region=region)
        scoped = [f for f in fixes if f.terminal_airport_icao in (None, airport)]
        return _fix_waypoint((scoped or fixes)[0]) if (scoped or fixes) else None


# ---------------------------------------------------------------------------
# Column lists that are used by more than one query
# ---------------------------------------------------------------------------

_NAVAID_COLUMNS = (
    "id, ident, kind, name, latitude, longitude, elevation_ft, frequency_khz, channel, "
    "range_nm, true_deg, mag_deg, glideslope_deg, magnetic_variation_deg, region_code, "
    "airport_icao, runway_ident, ils_category"
)

_FIX_COLUMNS = "id, ident, latitude, longitude, region_code, terminal_airport_icao, name"


# ---------------------------------------------------------------------------
# Row -> model
# ---------------------------------------------------------------------------


def _airport(row: sqlite3.Row) -> Airport:
    elevation_ft = _float(row, "elevation_ft")
    return Airport(
        icao=_text(row, "icao"),
        iata=_optional_text(row, "iata"),
        name=_text(row, "name"),
        city=_optional_text(row, "city"),
        country=_optional_text(row, "country"),
        region_code=_optional_text(row, "region_code"),
        position=GeoPosition(
            latitude=_float(row, "latitude"),
            longitude=_float(row, "longitude"),
            altitude_ft=elevation_ft,
        ),
        elevation_ft=elevation_ft,
        transition_altitude_ft=_optional_int(row, "transition_altitude_ft"),
        transition_level_ft=_optional_int(row, "transition_level_ft"),
        magnetic_variation_deg=_optional_float(row, "magnetic_variation_deg"),
        has_tower=bool(_optional_int(row, "has_tower")),
        runway_count=_optional_int(row, "runway_count") or 0,
        longest_runway_m=_positive(_optional_float(row, "longest_runway_m")),
        has_procedures=bool(_optional_int(row, "has_procedures")),
    )


def _summary(row: sqlite3.Row) -> AirportSummary:
    elevation_ft = _float(row, "elevation_ft")
    return AirportSummary(
        icao=_text(row, "icao"),
        iata=_optional_text(row, "iata"),
        name=_text(row, "name"),
        position=GeoPosition(
            latitude=_float(row, "latitude"),
            longitude=_float(row, "longitude"),
            altitude_ft=elevation_ft,
        ),
        elevation_ft=elevation_ft,
        longest_runway_m=_positive(_optional_float(row, "longest_runway_m")),
        has_procedures=bool(_optional_int(row, "has_procedures")),
    )


def _runway(row: sqlite3.Row, cifp: CifpRunway | None) -> Runway:
    """Build one runway end, applying the CIFP's threshold geometry where it exists.

    The CIFP wins on threshold and elevation because it is the datum the
    procedures themselves are built on. Taking ``apt.dat``'s threshold and the
    CIFP's approach legs would put a small, permanent, invisible offset between
    a placement and the procedure it claims to be on.
    """
    elevation_ft = _float(row, "elevation_ft")
    if cifp is not None and cifp.elevation_ft is not None:
        elevation_ft = cifp.elevation_ft

    threshold = GeoPosition(
        latitude=_float(row, "threshold_lat"),
        longitude=_float(row, "threshold_lon"),
        altitude_ft=elevation_ft,
    )
    if cifp is not None and cifp.threshold is not None:
        threshold = cifp.threshold.model_copy(update={"altitude_ft": elevation_ft})

    length_m = _float(row, "length_m")
    displaced_m = _optional_float(row, "displaced_threshold_m") or 0.0
    landing_distance_m = length_m - displaced_m
    surface = _optional_text(row, "surface")

    return Runway(
        airport_icao=_text(row, "airport_icao"),
        ident=_text(row, "ident"),
        threshold=threshold,
        true_bearing_deg=_float(row, "true_bearing_deg"),
        length_m=length_m,
        elevation_ft=elevation_ft,
        pavement_end=GeoPosition(
            latitude=_float(row, "end_lat"),
            longitude=_float(row, "end_lon"),
            altitude_ft=elevation_ft,
        ),
        displaced_threshold_m=displaced_m,
        landing_distance_m=landing_distance_m if landing_distance_m > 0.0 else None,
        opposite_ident=_optional_text(row, "opposite_ident"),
        width_m=_positive(_optional_float(row, "width_m")),
        surface=cast("RunwaySurface | None", surface if surface in _SURFACES else None),
        threshold_crossing_height_ft=(
            cifp.threshold_crossing_height_ft if cifp is not None else None
        ),
        ils=_ils(row, cifp),
    )


def _ils(row: sqlite3.Row, cifp: CifpRunway | None) -> Ils | None:
    """Assemble the ILS from ``earth_nav.dat``, with the CIFP's category on top."""
    frequency_khz = _optional_int(row, "loc_freq_khz")
    true_deg = _optional_float(row, "loc_true_deg")
    mag_deg = _optional_float(row, "loc_mag_deg")
    ident = _optional_text(row, "loc_ident")
    if ident is None or frequency_khz is None or true_deg is None or mag_deg is None:
        return None
    if not 108_000 <= frequency_khz <= 111_950:
        # Not a localizer frequency. Publishing it would fail Ils validation at
        # the worst possible moment, so the runway simply reports no ILS.
        return None

    glideslope_lat = _optional_float(row, "gs_lat")
    glideslope_lon = _optional_float(row, "gs_lon")
    glideslope_position = (
        GeoPosition(
            latitude=glideslope_lat,
            longitude=glideslope_lon,
            altitude_ft=_optional_float(row, "gs_elev_ft") or 0.0,
        )
        if glideslope_lat is not None and glideslope_lon is not None
        else None
    )

    return Ils(
        airport_icao=_text(row, "airport_icao"),
        runway_ident=_text(row, "ident"),
        localizer_ident=(
            cifp.localizer_ident if cifp is not None and cifp.localizer_ident else ident
        ),
        frequency_khz=frequency_khz,
        localizer_position=GeoPosition(
            latitude=_float(row, "loc_lat"),
            longitude=_float(row, "loc_lon"),
            altitude_ft=_optional_float(row, "loc_elev_ft") or 0.0,
        ),
        localizer_true_deg=true_deg,
        localizer_mag_deg=mag_deg,
        glideslope_deg=_positive(_optional_float(row, "gs_deg")),
        glideslope_position=glideslope_position,
        category=_ils_category(cifp.ils_category if cifp is not None else None),
        has_dme=_optional_int(row, "dme_id") is not None,
    )


def _ils_category(raw: str | None) -> Any:
    """Map the CIFP category code, defensively.

    Only ``1``/``2``/``3`` mean CAT I/II/III. Real data also carries blanks and
    letter codes for LDA, IGS and localizer-only installations, and a closed
    ``Literal`` fed straight from a source field is a ``ValidationError`` waiting
    for the first unusual airport.
    """
    return {"1": "I", "2": "II", "3": "III"}.get((raw or "").strip())


def _parking(row: sqlite3.Row) -> ParkingStand:
    kind = _text(row, "kind")
    operation = _optional_text(row, "operation")
    types = _optional_text(row, "aircraft_types")
    codes = _optional_text(row, "airline_codes")
    return ParkingStand(
        airport_icao=_text(row, "airport_icao"),
        name=_text(row, "name"),
        position=GeoPosition(
            latitude=_float(row, "latitude"),
            longitude=_float(row, "longitude"),
            altitude_ft=0.0,
        ),
        heading_true_deg=_float(row, "heading_true_deg") % 360.0,
        kind=cast("ParkingKind", kind if kind in _PARKING_KINDS else "misc"),
        aircraft_types=tuple(t for t in (types or "").split("|") if t),
        operation=cast(
            "ParkingOperation | None", operation if operation in _PARKING_OPERATIONS else None
        ),
        airline_codes=tuple(c for c in (codes or "").split() if c),
    )


def _navaid(row: sqlite3.Row) -> Navaid:
    kind = cast("NavaidKind", _text(row, "kind"))
    return Navaid(
        ident=_text(row, "ident"),
        kind=kind,
        name=_optional_text(row, "name"),
        position=GeoPosition(
            latitude=_float(row, "latitude"),
            longitude=_float(row, "longitude"),
            altitude_ft=_optional_float(row, "elevation_ft") or 0.0,
        ),
        frequency_khz=_optional_int(row, "frequency_khz"),
        channel=_optional_text(row, "channel"),
        range_nm=_optional_float(row, "range_nm"),
        magnetic_variation_deg=_optional_float(row, "magnetic_variation_deg"),
        region_code=_optional_text(row, "region_code"),
        airport_icao=_optional_text(row, "airport_icao"),
        runway_ident=_optional_text(row, "runway_ident"),
        tunable_radio=tunable_radio_for(kind),
    )


def _fix(row: sqlite3.Row) -> Fix:
    return Fix(
        ident=_text(row, "ident"),
        position=GeoPosition(
            latitude=_float(row, "latitude"),
            longitude=_float(row, "longitude"),
            altitude_ft=0.0,
        ),
        region_code=_optional_text(row, "region_code"),
        terminal_airport_icao=_optional_text(row, "terminal_airport_icao"),
        name=_optional_text(row, "name"),
    )


def _fix_waypoint(fix: Fix) -> Waypoint:
    return Waypoint(
        ident=fix.ident,
        kind="fix",
        position=fix.position,
        region_code=fix.region_code,
        airport_icao=fix.terminal_airport_icao,
        name=fix.name,
    )


def _navaid_waypoint(navaids: Sequence[Navaid]) -> Waypoint | None:
    if not navaids:
        return None
    navaid = navaids[0]
    return Waypoint(
        ident=navaid.ident,
        kind=_NAVAID_WAYPOINT_KIND.get(navaid.kind, "fix"),
        position=navaid.position,
        region_code=navaid.region_code,
        airport_icao=navaid.airport_icao,
        name=navaid.name,
    )


def _procedure_summary(procedure: Procedure) -> ProcedureSummary:
    return ProcedureSummary(
        airport_icao=procedure.airport_icao,
        kind=procedure.kind,
        ident=procedure.ident,
        transition=procedure.transition,
        runway_idents=procedure.runway_idents,
        approach_type=procedure.approach_type,
        leg_count=len(procedure.legs),
        positionable_leg_count=sum(1 for leg in procedure.legs if leg.is_positionable),
    )


def _procedure_sort_key(procedure: Procedure) -> tuple[str, str, str]:
    return (procedure.kind, procedure.ident, procedure.transition or "")


# ---------------------------------------------------------------------------
# Spatial and metadata helpers
# ---------------------------------------------------------------------------


def _bounding_boxes(
    centre: GeoPosition, radius_nm: float
) -> list[tuple[float, float, float, float]]:
    """Latitude/longitude rectangles that certainly contain the circle.

    A box that crosses the antimeridian is split into two range predicates,
    because ``longitude BETWEEN 179 AND -179`` matches nothing. Near the poles
    the longitude half-width stops being meaningful, so the latitude band alone
    prefilters and the geodesic refine does the rest.
    """
    delta_lat = radius_nm / 60.0
    lat_min = max(centre.latitude - delta_lat, -90.0)
    lat_max = min(centre.latitude + delta_lat, 90.0)

    peak = max(abs(lat_min), abs(lat_max))
    if peak >= _POLAR_LATITUDE_DEG:
        return [(lat_min, lat_max, -180.0, 180.0)]

    delta_lon = radius_nm / (60.0 * math.cos(math.radians(peak)))
    if delta_lon >= 180.0:
        return [(lat_min, lat_max, -180.0, 180.0)]

    lon_min = centre.longitude - delta_lon
    lon_max = centre.longitude + delta_lon
    if lon_min < -180.0:
        return [(lat_min, lat_max, lon_min + 360.0, 180.0), (lat_min, lat_max, -180.0, lon_max)]
    if lon_max > 180.0:
        return [(lat_min, lat_max, lon_min, 180.0), (lat_min, lat_max, -180.0, lon_max - 360.0)]
    return [(lat_min, lat_max, lon_min, lon_max)]


def _kind_filter(kinds: Collection[NavaidKind] | None, parameters: list[Any]) -> str:
    if not kinds:
        return ""
    parameters.extend(kinds)
    placeholders = ", ".join("?" for _ in kinds)
    return f" AND kind IN ({placeholders})"


def _cifp_idents(root: Path) -> frozenset[str]:
    """Which airports have a CIFP file, from two directory listings.

    A ``stat()`` per airport would be 60 000 syscalls on Windows for a flag that
    only greys out a tab. Two listings answer the same question once.
    """
    idents: set[str] = set()
    for relative in ("Custom Data/CIFP", "Resources/default data/CIFP"):
        directory = root / relative
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        idents.update(e.stem.upper() for e in entries if e.suffix.lower() == ".dat")
    return frozenset(idents)


def _read_meta(path: Path) -> dict[str, str]:
    try:
        connection = sqlite3.connect(read_only_uri(path), uri=True)
    except sqlite3.Error:  # pragma: no cover - the file was just written
        return {}
    try:
        rows = connection.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error:  # pragma: no cover
        return {}
    finally:
        connection.close()
    return {str(key): str(value) for key, value in rows}


def _as_int(text: str | None) -> int | None:
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _as_date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _as_datetime(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0.0 else None


def _text(row: sqlite3.Row, column: str) -> str:
    return str(row[column])


def _optional_text(row: sqlite3.Row, column: str) -> str | None:
    value = row[column]
    return str(value) if value is not None else None


def _float(row: sqlite3.Row, column: str) -> float:
    return float(row[column])


def _optional_float(row: sqlite3.Row, column: str) -> float | None:
    value = row[column]
    return float(value) if value is not None else None


def _optional_int(row: sqlite3.Row, column: str) -> int | None:
    value = row[column]
    return int(value) if value is not None else None
