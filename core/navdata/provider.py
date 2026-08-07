"""The navdata contract.

This module is to the static world what :mod:`core.sim_adapter` is to the live
simulator, and it is deliberately unrelated to it: no method here takes or
returns a type from ``core.sim_adapter``, neither module imports the other, and
the two are wired independently in ``server/deps.py``.

That separation is what lets an MSFS provider satisfy the same protocol in a
later phase without anything in ``core/``, ``server/`` or ``ui/`` changing —
and what lets a user fly one simulator while reading another's navdata tree.

**Query methods are synchronous.** There is nothing to await: this reads a local
SQLite file and, occasionally, a 7 KB text file. ``sqlite3`` is blocking and has
no async API, so wrapping each call would add a thread hop to a query that
completes in microseconds. FastAPI's answer to a blocking call is to declare the
route ``def`` rather than ``async def``, which runs it in the threadpool; that is
a one-line convention in ``server/`` and it costs nothing. Only the index build
is long-running, and it is explicitly a job with progress and cancellation.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from typing import Protocol, runtime_checkable

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
)

__all__ = [
    "NavdataIndexError",
    "NavdataProvider",
    "NavdataUnavailable",
]


class NavdataUnavailable(RuntimeError):
    """Raised when a query is made against a provider that has no usable data.

    **The UI is expected to gate on** :meth:`NavdataProvider.status` **, not to
    catch this.** Seeing it means a caller ignored the status — a bug in the
    caller, exactly as :class:`~core.sim_adapter.CapabilityNotSupported` is.
    """

    def __init__(self, provider_name: str, reason: str) -> None:
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(
            f"Navdata provider {provider_name!r} has no usable data: {reason} "
            f"Check status() before querying."
        )


class NavdataIndexError(RuntimeError):
    """Raised when an index build fails outright — I/O error, disk full, corrupt source.

    A *record* that cannot be parsed never raises: the build logs it, skips it
    and counts it. Real navdata always contains a handful of malformed rows, and
    an instructor station that refuses to start because one airport in Chad has
    a bad runway row is useless. This exception is for the build itself failing.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@runtime_checkable
class NavdataProvider(Protocol):
    """Read-only access to the navigation world.

    Implementations must be import-safe: constructing a provider performs no
    I/O. Nothing is read until :meth:`status` or a query is called, and no index
    is built until :meth:`ensure_index` is called.

    **Not-found is never an exception.** A missing airport, runway, navaid, fix
    or procedure returns ``None`` or an empty list. Exceptions are for *broken*,
    never for *absent* — see :class:`NavdataUnavailable` and
    :class:`NavdataIndexError`.
    """

    # --- Identity and lifecycle -------------------------------------------

    @property
    def name(self) -> str:
        """Short provider identifier: ``"xplane_native"``, ``"in_memory"``, ``"msfs_bgl"``."""
        ...

    def status(self) -> NavdataStatus:
        """What this provider can currently answer. Cheap, thread-safe, never raises.

        Returns an immutable snapshot, so it is safe to call from a request
        thread while a build runs in another.
        """
        ...

    def ensure_index(
        self,
        *,
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
        force: bool = False,
    ) -> NavdataStatus:
        """Build the index unless the cache key already matches.

        Idempotent, long-running, and safe to call from a worker thread.

        Args:
            progress: Called with each progress frame. Throttled by the
                implementation — a 12-million-line source must not emit a frame
                per line. The callback runs on the **calling** thread; bridging
                it into an event loop is the caller's job.
            cancel: Checked periodically. When set, the build abandons its
                partial work, publishes nothing and leaves the previous index
                exactly as it was. An ``Event`` rather than a callback return
                value, because a callback typed ``-> None`` cannot signal
                anything and the canceller is not on the build's thread.
            force: Rebuild even when the cache key matches.

        Raises:
            NavdataIndexError: The build itself failed.
        """
        ...

    # --- Airports ----------------------------------------------------------

    def get_airport(self, icao: str) -> Airport | None:
        """One airport by ICAO code, or ``None``."""
        ...

    def search_airports(self, query: str, *, limit: int = 20) -> list[AirportSummary]:
        """Type-ahead over ICAO, IATA and name. Ranked, always bounded."""
        ...

    def airports_near(
        self, centre: GeoPosition, radius_nm: float, *, limit: int = 50
    ) -> list[AirportSummary]:
        """Airports within ``radius_nm``, nearest first."""
        ...

    # --- Runways -----------------------------------------------------------

    def get_runways(self, icao: str) -> list[Runway]:
        """Every runway END of an airport, sorted by ident.

        18L and 36R are two :class:`~core.models.Runway` objects, because a
        placement is always relative to one end.
        """
        ...

    def get_runway(self, icao: str, ident: str) -> Runway | None:
        """One runway end.

        ``ident`` is accepted in either source's spelling — ``"18L"`` or
        ``"RW18L"`` — and always comes back as ``"18L"``.
        """
        ...

    # --- Parking -----------------------------------------------------------

    def get_parking(self, icao: str, *, kind: ParkingKind | None = None) -> list[ParkingStand]:
        """Parking positions of an airport, optionally filtered by kind."""
        ...

    # --- Procedures --------------------------------------------------------

    def get_procedures(
        self, icao: str, *, kind: ProcedureKind | None = None
    ) -> list[ProcedureSummary]:
        """Summaries only — a large airport has 100+ procedures and the UI lists before it draws."""
        ...

    def get_procedure(
        self,
        icao: str,
        kind: ProcedureKind,
        ident: str,
        transition: str | None = None,
    ) -> Procedure | None:
        """One procedure with its legs fully resolved: every positionable leg carries its fix."""
        ...

    # --- Navaids and fixes -------------------------------------------------

    def get_navaids(
        self,
        ident: str,
        *,
        region: str | None = None,
        kinds: Collection[NavaidKind] | None = None,
    ) -> list[Navaid]:
        """Navaids by identifier — a **list**, because navaid idents are not globally unique."""
        ...

    def navaids_near(
        self,
        centre: GeoPosition,
        radius_nm: float,
        *,
        kinds: Collection[NavaidKind] | None = None,
        limit: int = 50,
    ) -> list[Navaid]:
        """Navaids within ``radius_nm``, nearest first."""
        ...

    def get_ils(self, icao: str, runway_ident: str) -> Ils | None:
        """The ILS serving one runway end, ready to feed ``AircraftSetup``."""
        ...

    def get_fixes(
        self,
        ident: str,
        *,
        region: str | None = None,
        terminal_airport: str | None = None,
    ) -> list[Fix]:
        """Fixes by identifier, optionally scoped by region or terminal airport."""
        ...

    def fixes_near(self, centre: GeoPosition, radius_nm: float, *, limit: int = 50) -> list[Fix]:
        """Fixes within ``radius_nm``, nearest first."""
        ...

    def resolve_fix(self, ref: FixRef) -> Waypoint | None:
        """Turn a 4-part ARINC key into a coordinate. The single place that mapping lives."""
        ...

    # --- Holds -------------------------------------------------------------

    def get_holds(
        self,
        *,
        fix_ident: str | None = None,
        region: str | None = None,
        airport_icao: str | None = None,
    ) -> list[Hold]:
        """Published holds from ``earth_hold.dat``.

        Procedure holds — the ``HM``/``HA``/``HF`` legs — arrive through
        :meth:`get_procedure` instead, and the two sets are deliberately **not**
        merged: they overlap without being the same set, and silently unioning
        them would duplicate holds with no way for the UI to say which chart the
        instructor is looking at.
        """
        ...
