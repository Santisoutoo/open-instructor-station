"""``/api/navdata/*`` — a read-only façade over :class:`~core.navdata.provider.NavdataProvider`.

Three things about this module are deliberate.

**The routes are ``def``, not ``async def``.** Every query on the provider
protocol is synchronous by contract: it reads a local SQLite file, and
``sqlite3`` has no async API. FastAPI runs a synchronous route in its
threadpool, which is exactly right for a blocking call that completes in
microseconds; declaring these ``async def`` would run them on the event loop and
stall the ~4 Hz telemetry push for every request.

**Absent is 404, broken is 503.** The provider never raises for a missing
airport — it returns ``None`` — so a 404 here means "no such thing", full stop.
:class:`~core.navdata.provider.NavdataUnavailable` becomes a 503 carrying its
reason, a ``Retry-After`` and the whole of ``status()``, and reaching it means a
caller skipped ``GET /api/navdata/status``. It is the navdata twin of the 501 the
adapter routes return, and the UI is expected to have disabled the panel long
before either can happen — but a tablet that joined mid-build did nothing wrong,
so it gets the state and a wait rather than an opaque error. See
:func:`navdata_unavailable_handler`.

**The index build is a job, not a request.** It takes minutes over a real
install, so ``POST /api/navdata/index`` starts a worker thread and returns the
current status immediately. Progress is read by polling ``GET
/api/navdata/status`` — the provider publishes each frame into its own status —
rather than over a second WebSocket: the build happens once, the frames are
coarse, and a socket would be more machinery than the problem has.
"""

from __future__ import annotations

import logging
import threading
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from core.models import GeoPosition, Ils, Runway
from core.navdata.models import (
    Airport,
    AirportSummary,
    Fix,
    Hold,
    Navaid,
    NavaidKind,
    NavdataStatus,
    ParkingKind,
    ParkingStand,
    Procedure,
    ProcedureKind,
    ProcedureSummary,
)
from core.navdata.provider import NavdataProvider, NavdataUnavailable
from server.deps import get_navdata

__all__ = [
    "BUILDING_RETRY_AFTER_S",
    "NAVDATA_UNAVAILABLE_STATUS",
    "UNAVAILABLE_RETRY_AFTER_S",
    "cancel_index_build",
    "navdata_unavailable_handler",
    "router",
]

logger = logging.getLogger(__name__)

#: Status for "this provider has no usable data". 503 rather than 4xx: the
#: request is well-formed and the *server* has nothing to answer it with, and
#: unlike a 501 it is expected to become answerable once the index is built.
NAVDATA_UNAVAILABLE_STATUS = 503

#: ``Retry-After`` while the index is *building*, seconds. Short, because the
#: thing the client is waiting for is finishing on its own.
BUILDING_RETRY_AFTER_S = 5

#: ``Retry-After`` while the provider is *unavailable* or in *error*, seconds.
#: Long, because a human has to act — point the station at an install, or fix a
#: broken one — and hammering the endpoint will not make that happen sooner.
UNAVAILABLE_RETRY_AFTER_S = 60

router = APIRouter(prefix="/api/navdata", tags=["navdata"])

#: The single in-flight index build. Module state rather than app state because
#: there is exactly one provider singleton behind it, and a second concurrent
#: build over the same SQLite file is never something a caller wants.
_build_lock = threading.Lock()
_build_thread: threading.Thread | None = None
_build_cancel = threading.Event()


def _provider() -> NavdataProvider:
    """The process-wide provider, as a function so tests can patch one place."""
    return get_navdata()


def _found[T](value: T | None, what: str) -> T:
    """Return ``value``, or raise 404 naming what was missing."""
    if value is None:
        raise HTTPException(status_code=404, detail=f"{what} is not in the navigation index.")
    return value


@router.get("/status", response_model=NavdataStatus)
def status() -> NavdataStatus:
    """What the navdata provider can currently answer, and why not when it cannot.

    This is to navdata what ``GET /api/capabilities`` is to the simulator: the
    UI gates the whole Position panel on it and states the reason, so an
    instructor never discovers missing navdata by clicking a control that fails.
    """
    return _provider().status()


@router.post("/index", response_model=NavdataStatus)
def build_index(force: bool = Query(default=False)) -> NavdataStatus:
    """Start building the navigation index, and report the status right away.

    Idempotent: calling it again while a build is running is a no-op that
    returns the current status. An impatient tablet retrying cannot turn this
    into a fork bomb over one SQLite file.
    """
    global _build_thread

    provider = _provider()
    with _build_lock:
        if _build_thread is not None and _build_thread.is_alive():
            return provider.status()

        _build_cancel.clear()

        def run() -> None:
            try:
                provider.ensure_index(cancel=_build_cancel, force=force)
            except Exception:
                # The provider records the failure in its own status, which is
                # what the UI reads. Logging is all this thread can usefully do.
                logger.exception("Navdata index build failed")

        _build_thread = threading.Thread(target=run, name="navdata-index", daemon=True)
        _build_thread.start()

    return provider.status()


def cancel_index_build() -> None:
    """Ask a running build to abandon its partial work. For shutdown and tests."""
    _build_cancel.set()


@router.get("/airports", response_model=list[AirportSummary])
def search_airports(
    q: str = Query(min_length=1, description="ICAO, IATA or part of the name."),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AirportSummary]:
    """Type-ahead over every airport in the index. Ranked, always bounded."""
    return _provider().search_airports(q, limit=limit)


@router.get("/airports/near", response_model=list[AirportSummary])
def airports_near(
    lat: float = Query(ge=-90.0, le=90.0),
    lon: float = Query(ge=-180.0, le=180.0),
    radius_nm: float = Query(default=50.0, gt=0.0, le=1000.0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AirportSummary]:
    """Airports within ``radius_nm`` of a point, nearest first."""
    centre = GeoPosition(latitude=lat, longitude=lon)
    return _provider().airports_near(centre, radius_nm, limit=limit)


@router.get("/airports/{icao}", response_model=Airport)
def get_airport(icao: str) -> Airport:
    """One airport by ICAO code."""
    return _found(_provider().get_airport(icao), f"Airport {icao.upper()!r}")


@router.get("/airports/{icao}/runways", response_model=list[Runway])
def get_runways(icao: str) -> list[Runway]:
    """Every runway **end** of an airport.

    18L and 36R are two entries, not one: a placement is always relative to one
    end, and the UI offers one button per end for exactly that reason.
    """
    return _provider().get_runways(icao)


@router.get("/airports/{icao}/runways/{runway_ident}/ils", response_model=Ils)
def get_ils(icao: str, runway_ident: str) -> Ils:
    """The ILS serving one runway end."""
    return _found(
        _provider().get_ils(icao, runway_ident),
        f"An ILS for {icao.upper()} runway {runway_ident.upper()}",
    )


@router.get("/airports/{icao}/parking", response_model=list[ParkingStand])
def get_parking(icao: str, kind: ParkingKind | None = None) -> list[ParkingStand]:
    """Gates, stands, tie-downs and hangars, optionally filtered by kind."""
    return _provider().get_parking(icao, kind=kind)


@router.get("/airports/{icao}/procedures", response_model=list[ProcedureSummary])
def get_procedures(icao: str, kind: ProcedureKind | None = None) -> list[ProcedureSummary]:
    """Procedure summaries — enough to list them without parsing every leg."""
    return _provider().get_procedures(icao, kind=kind)


@router.get("/airports/{icao}/procedures/{kind}/{ident}", response_model=Procedure)
def get_procedure(
    icao: str,
    kind: ProcedureKind,
    ident: str,
    transition: str | None = None,
) -> Procedure:
    """One procedure with every leg resolved.

    Legs that carry no defensible coordinate come back too, flagged
    ``is_positionable = false`` with a reason: an instructor reading a SID needs
    to see the climb leg even though it can never be a placement.
    """
    return _found(
        _provider().get_procedure(icao, kind, ident, transition),
        f"Procedure {ident.upper()!r} at {icao.upper()}",
    )


@router.get("/navaids", response_model=list[Navaid])
def get_navaids(
    ident: str | None = Query(default=None, min_length=1, description="VOR/NDB/DME identifier."),
    region: str | None = Query(default=None, description="ICAO region code, e.g. 'LE'."),
    lat: float | None = Query(default=None, ge=-90.0, le=90.0),
    lon: float | None = Query(default=None, ge=-180.0, le=180.0),
    radius_nm: float = Query(default=50.0, gt=0.0, le=1000.0),
    kinds: Annotated[list[NavaidKind] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Navaid]:
    """Navaids by identifier, or every navaid near a point.

    **Two query forms, one path**, because they answer the same question from
    the two directions an instructor asks it: "where is BRA?" and "what can I
    tune from here?". Exactly one of ``ident`` and ``lat``/``lon`` must be given
    — sending both would leave the server to invent a precedence, and sending
    neither would ask for every navaid on Earth.

    A list either way: navaid identifiers are **not** globally unique, so the
    single-ident form returns every match sorted by ident then region, and the
    caller disambiguates with ``region``.
    """
    if ident is not None and lat is None and lon is None:
        return _provider().get_navaids(ident, region=region, kinds=kinds)
    if ident is None and lat is not None and lon is not None:
        centre = GeoPosition(latitude=lat, longitude=lon)
        return _provider().navaids_near(centre, radius_nm, kinds=kinds, limit=limit)
    raise HTTPException(
        status_code=422,
        detail=(
            "Give either 'ident' (with an optional 'region') or 'lat' and 'lon' "
            "(with an optional 'radius_nm'), but not both and not neither."
        ),
    )


@router.get("/fixes", response_model=list[Fix])
def get_fixes(
    ident: str = Query(min_length=1),
    region: str | None = None,
    terminal_airport: str | None = None,
) -> list[Fix]:
    """Fixes by identifier — a list, because fix idents are not globally unique."""
    return _provider().get_fixes(ident, region=region, terminal_airport=terminal_airport)


@router.get("/holds", response_model=list[Hold])
def get_holds(
    fix_ident: str | None = None,
    region: str | None = None,
    airport_icao: str | None = None,
) -> list[Hold]:
    """Published holds from ``earth_hold.dat``.

    Procedure holds — the ``HM``/``HA``/``HF`` legs — arrive through the
    procedure endpoint instead, and the two sets are deliberately not merged.
    """
    return _provider().get_holds(fix_ident=fix_ident, region=region, airport_icao=airport_icao)


def navdata_unavailable_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Turn "this provider has no usable data" into a 503 carrying its reason.

    Registered once on the app rather than repeated as a ``try`` in twelve
    routes: every one of them can raise it and every one of them would answer
    identically.

    **The body carries the full ``status()``, not only a message.** A client
    that raced the index build asks a question and gets an answer to a slightly
    different one — *this is the state, come back when it says ready* — instead
    of an opaque error it has to interpret. It is the same object
    ``GET /api/navdata/status`` serves, so a UI can feed it straight into the
    gate it already has rather than having a second unavailability path.

    **And a ``Retry-After``, whose value is the difference between waiting and
    giving up.** A build finishes on its own, so five seconds is the honest
    interval; an absent or broken install needs a human, so sixty is, and
    retrying faster only burns the tablet's battery.

    ``def``, not ``async def``, for the same reason the routes are: reading the
    status is a synchronous provider call and Starlette runs a sync handler in
    its threadpool.
    """
    reason = exc.reason if isinstance(exc, NavdataUnavailable) else str(exc)
    status = _provider().status()
    retry_after = (
        BUILDING_RETRY_AFTER_S if status.state == "building" else UNAVAILABLE_RETRY_AFTER_S
    )
    return JSONResponse(
        status_code=NAVDATA_UNAVAILABLE_STATUS,
        content={"detail": reason, "status": status.model_dump(mode="json")},
        headers={"Retry-After": str(retry_after)},
    )
