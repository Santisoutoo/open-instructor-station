"""A :class:`~core.navdata.provider.NavdataProvider` built from objects in memory.

This exists for the same two reasons :class:`~adapters.fake.FakeSimAdapter`
does:

1. **It lets a test build exactly the world a case needs.** A placement test
   wants one runway on a known bearing with hand-computable geometry, not the
   31 269 airports of a real install.
2. **It forces the abstraction to be real.** An interface with one
   implementation is a suggestion. A second implementation that must satisfy the
   same contract makes X-Plane file-format assumptions impossible to smuggle
   into ``core/`` — they simply fail here.

It is always ``ready``: there is nothing to index and nothing to discover, so
:meth:`InMemoryNavdataProvider.ensure_index` is a no-op that reports what it
already holds.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection, Iterable, Sequence

from core.geodesy import distance_and_bearing
from core.models import GeoPosition, Ils, Runway
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
    ParkingStand,
    Procedure,
    ProcedureKind,
    ProcedureSummary,
    Waypoint,
    WaypointKind,
)
from core.navdata.normalize import (
    normalize_icao,
    normalize_runway_ident,
    normalize_search_text,
)

__all__ = ["InMemoryNavdataProvider"]

PROVIDER_NAME = "in_memory"


class InMemoryNavdataProvider:
    """Serve navdata from collections handed to the constructor.

    Every collection is optional: a test that only cares about runways passes
    runways. Nothing is validated against anything else — the point is to build
    a *specific* world, including deliberately incomplete ones.
    """

    def __init__(
        self,
        *,
        airports: Iterable[Airport] = (),
        runways: Iterable[Runway] = (),
        parking: Iterable[ParkingStand] = (),
        navaids: Iterable[Navaid] = (),
        fixes: Iterable[Fix] = (),
        holds: Iterable[Hold] = (),
        procedures: Iterable[Procedure] = (),
    ) -> None:
        self._airports: tuple[Airport, ...] = tuple(airports)
        self._runways: tuple[Runway, ...] = tuple(runways)
        self._parking: tuple[ParkingStand, ...] = tuple(parking)
        self._navaids: tuple[Navaid, ...] = tuple(navaids)
        self._fixes: tuple[Fix, ...] = tuple(fixes)
        self._holds: tuple[Hold, ...] = tuple(holds)
        self._procedures: tuple[Procedure, ...] = tuple(procedures)

    # --- Identity and lifecycle -------------------------------------------

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def status(self) -> NavdataStatus:
        return NavdataStatus(
            state="ready",
            reason=None,
            provider=PROVIDER_NAME,
            airport_count=len(self._airports),
            runway_count=len(self._runways),
            navaid_count=len(self._navaids),
            fix_count=len(self._fixes),
        )

    def ensure_index(
        self,
        *,
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
        force: bool = False,
    ) -> NavdataStatus:
        """Nothing to build. Reports the current status without touching the callback.

        Deliberately silent rather than emitting a single 100% frame: a UI that
        shows a progress bar for a provider that has no build would be lying
        about what happened.
        """
        del progress, cancel, force
        return self.status()

    # --- Airports ----------------------------------------------------------

    def get_airport(self, icao: str) -> Airport | None:
        wanted = normalize_icao(icao)
        return next((a for a in self._airports if a.icao == wanted), None)

    def search_airports(self, query: str, *, limit: int = 20) -> list[AirportSummary]:
        needle = normalize_search_text(query)
        if not needle:
            return []
        upper = needle.upper()

        ranked: list[tuple[int, float, str, Airport]] = []
        for airport in self._airports:
            rank = _search_rank(airport, upper, needle)
            if rank is None:
                continue
            # Longest runway descending: an instructor typing "madrid" wants
            # LEMD above a Madrid airstrip.
            ranked.append((rank, -(airport.longest_runway_m or 0.0), airport.icao, airport))

        ranked.sort(key=lambda row: (row[0], row[1], row[2]))
        return [_summarise(row[3]) for row in ranked[:limit]]

    def airports_near(
        self, centre: GeoPosition, radius_nm: float, *, limit: int = 50
    ) -> list[AirportSummary]:
        near = _within_radius(self._airports, centre, radius_nm, lambda a: a.position)
        return [_summarise(airport) for airport, _ in near[:limit]]

    # --- Runways -----------------------------------------------------------

    def get_runways(self, icao: str) -> list[Runway]:
        wanted = normalize_icao(icao)
        return sorted((r for r in self._runways if r.airport_icao == wanted), key=lambda r: r.ident)

    def get_runway(self, icao: str, ident: str) -> Runway | None:
        wanted = normalize_runway_ident(ident)
        return next((r for r in self.get_runways(icao) if r.ident == wanted), None)

    # --- Parking -----------------------------------------------------------

    def get_parking(self, icao: str, *, kind: ParkingKind | None = None) -> list[ParkingStand]:
        wanted = normalize_icao(icao)
        stands = [s for s in self._parking if s.airport_icao == wanted]
        if kind is not None:
            stands = [s for s in stands if s.kind == kind]
        return sorted(stands, key=lambda s: s.name)

    # --- Procedures --------------------------------------------------------

    def get_procedures(
        self, icao: str, *, kind: ProcedureKind | None = None
    ) -> list[ProcedureSummary]:
        wanted = normalize_icao(icao)
        matches = [p for p in self._procedures if p.airport_icao == wanted]
        if kind is not None:
            matches = [p for p in matches if p.kind == kind]
        return [_summarise_procedure(p) for p in sorted(matches, key=_procedure_sort_key)]

    def get_procedure(
        self,
        icao: str,
        kind: ProcedureKind,
        ident: str,
        transition: str | None = None,
    ) -> Procedure | None:
        wanted = normalize_icao(icao)
        return next(
            (
                p
                for p in self._procedures
                if p.airport_icao == wanted
                and p.kind == kind
                and p.ident == ident
                and p.transition == transition
            ),
            None,
        )

    # --- Navaids and fixes -------------------------------------------------

    def get_navaids(
        self,
        ident: str,
        *,
        region: str | None = None,
        kinds: Collection[NavaidKind] | None = None,
    ) -> list[Navaid]:
        wanted = ident.strip().upper()
        matches = [n for n in self._navaids if n.ident == wanted]
        if region is not None:
            matches = [n for n in matches if n.region_code == region]
        if kinds is not None:
            matches = [n for n in matches if n.kind in kinds]
        return sorted(matches, key=lambda n: (n.ident, n.region_code or ""))

    def navaids_near(
        self,
        centre: GeoPosition,
        radius_nm: float,
        *,
        kinds: Collection[NavaidKind] | None = None,
        limit: int = 50,
    ) -> list[Navaid]:
        pool = (
            self._navaids if kinds is None else tuple(n for n in self._navaids if n.kind in kinds)
        )
        near = _within_radius(pool, centre, radius_nm, lambda n: n.position)
        return [navaid for navaid, _ in near[:limit]]

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
        wanted = ident.strip().upper()
        matches = [f for f in self._fixes if f.ident == wanted]
        if region is not None:
            matches = [f for f in matches if f.region_code == region]
        if terminal_airport is not None:
            wanted_airport = normalize_icao(terminal_airport)
            matches = [f for f in matches if f.terminal_airport_icao == wanted_airport]
        return sorted(matches, key=lambda f: (f.ident, f.region_code or ""))

    def fixes_near(self, centre: GeoPosition, radius_nm: float, *, limit: int = 50) -> list[Fix]:
        near = _within_radius(self._fixes, centre, radius_nm, lambda f: f.position)
        return [fix for fix, _ in near[:limit]]

    def resolve_fix(self, ref: FixRef) -> Waypoint | None:
        """Resolve a 4-part ARINC key against whatever this provider holds.

        The section/subsection table is the same one the indexed provider uses;
        here it selects a Python list instead of a SQL table.
        """
        section = ref.section.strip().upper()
        subsection = ref.subsection.strip().upper()

        if section == "D":
            kinds: tuple[NavaidKind, ...] = (
                ("ndb",) if subsection == "B" else ("vor", "vor_dme", "vortac", "dme", "tacan")
            )
            return _first_navaid_waypoint(
                self.get_navaids(ref.ident, region=ref.region_code, kinds=kinds)
            )

        if section == "E":
            return _fix_waypoint(
                next(
                    (
                        f
                        for f in self.get_fixes(ref.ident, region=ref.region_code)
                        if f.terminal_airport_icao is None
                    ),
                    None,
                )
            )

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
        matches = list(self._holds)
        if fix_ident is not None:
            wanted = fix_ident.strip().upper()
            matches = [h for h in matches if h.fix.ident == wanted]
        if region is not None:
            matches = [h for h in matches if h.fix.region_code == region]
        if airport_icao is not None:
            wanted_airport = normalize_icao(airport_icao)
            matches = [h for h in matches if h.airport_icao == wanted_airport]
        return matches

    # --- Internals ---------------------------------------------------------

    def _resolve_terminal(self, ref: FixRef, subsection: str) -> Waypoint | None:
        """Resolve the ``P`` section: everything scoped to one airport."""
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
            kinds: tuple[NavaidKind, ...] = ("localizer",) if subsection == "I" else ("ndb",)
            candidates = [
                n
                for n in self.get_navaids(ref.ident, region=ref.region_code, kinds=kinds)
                if airport_icao is None or n.airport_icao in (None, normalize_icao(airport_icao))
            ]
            return _first_navaid_waypoint(candidates)

        # "C" and anything else terminal: a waypoint scoped to this airport.
        if airport_icao is None:
            return None
        return _fix_waypoint(
            next(
                iter(
                    self.get_fixes(ref.ident, region=ref.region_code, terminal_airport=airport_icao)
                ),
                None,
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _search_rank(airport: Airport, upper: str, needle: str) -> int | None:
    """Rank one airport against a search term, or ``None`` when it does not match."""
    if airport.icao == upper:
        return 0
    if airport.icao.startswith(upper):
        return 1
    if airport.iata is not None and airport.iata == upper:
        return 2
    name_norm = normalize_search_text(airport.name)
    if name_norm.startswith(needle):
        return 3
    if needle in name_norm:
        return 4
    return None


def _summarise(airport: Airport) -> AirportSummary:
    return AirportSummary(
        icao=airport.icao,
        iata=airport.iata,
        name=airport.name,
        position=airport.position,
        elevation_ft=airport.elevation_ft,
        longest_runway_m=airport.longest_runway_m,
        has_procedures=airport.has_procedures,
    )


def _summarise_procedure(procedure: Procedure) -> ProcedureSummary:
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


def _within_radius[T](
    items: Sequence[T],
    centre: GeoPosition,
    radius_nm: float,
    position_of: Callable[[T], GeoPosition],
) -> list[tuple[T, float]]:
    """Exact geodesic filter, nearest first.

    The indexed provider prefilters with a bounding box before doing this; here
    the collection is small enough that the box would be pure overhead.
    """
    measured = []
    for item in items:
        distance_nm, _ = distance_and_bearing(centre, position_of(item))
        if distance_nm <= radius_nm:
            measured.append((item, distance_nm))
    measured.sort(key=lambda row: row[1])
    return measured


def _fix_waypoint(fix: Fix | None) -> Waypoint | None:
    if fix is None:
        return None
    return Waypoint(
        ident=fix.ident,
        kind="fix",
        position=fix.position,
        region_code=fix.region_code,
        airport_icao=fix.terminal_airport_icao,
        name=fix.name,
    )


def _first_navaid_waypoint(navaids: Sequence[Navaid]) -> Waypoint | None:
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


_NAVAID_WAYPOINT_KIND: dict[NavaidKind, WaypointKind] = {
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
