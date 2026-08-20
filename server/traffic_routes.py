"""``/api/traffic/*`` and ``WS /ws/traffic`` — spawn, despawn and watch AI traffic.

Per ``docs/designs/ai-traffic.md`` §2, §3.5 and §6.3.

**One spawn endpoint, one discriminated union (D7).** A
:data:`~core.traffic.TrafficSpawnRequest` names an instructor's intent
(``tcas_conflict`` / ``runway_incursion`` / ``approach_sequence`` /
``taxi_traffic`` / ``custom``) and :func:`_resolve_spawn_requests` turns it into
one or more concrete :class:`~core.traffic.TrafficTrack`s by calling the
``core/`` geometry builders — the resolution lives here and not in ``core/``
because the TCAS and incursion shapes read the user aircraft's state through the
adapter, and anything that awaits ``SimAdapter`` lives in ``server/``.

**Reads are never gated; writes are (§2.1).** ``GET /status`` and
``WS /traffic`` degrade to an empty contact list on an adapter without
``can_spawn_traffic`` — the ``/api/failures/status`` posture — while ``/spawn``,
``DELETE /{traffic_id}`` and ``/clear`` refuse up front with 501 and a stated
reason. Nobody should reach the 501s: the panel disables spawn controls from
``GET /api/capabilities`` before a request is ever sent.

**Timing is computed once, at spawn time (D8).** The TCAS and incursion builders
read the user aircraft's state exactly once, when the instructor taps Spawn —
there is no live server-side scheduler re-aiming tracks afterwards. A student
whose speed changes materially after spawn drifts the timing; that is stated in
the builders' own docstrings, not hidden here.
"""

from __future__ import annotations

import logging
from contextlib import suppress

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, TypeAdapter

from core.models import Runway
from core.navdata.provider import NavdataProvider
from core.sim_adapter import CapabilityNotSupported, SimAdapter
from core.traffic import (
    ApproachSequenceSpawnRequest,
    RunwayIncursionSpawnRequest,
    TaxiTrafficSpawnRequest,
    TcasConflictSpawnRequest,
    TrafficCapacityExceeded,
    TrafficContact,
    TrafficSpawnRequest,
    TrafficTrack,
    approach_sequence_tracks,
    runway_incursion_track,
    taxi_traffic_track,
    tcas_conflict_track,
)
from server.deps import get_adapter, get_navdata

__all__ = [
    "CAPABILITY_UNAVAILABLE_STATUS",
    "TRAFFIC_AT_CAPACITY_STATUS",
    "TRAFFIC_STREAM_INTERVAL_S",
    "TrafficSpawnResult",
    "TrafficStatus",
    "router",
]

logger = logging.getLogger(__name__)

#: Mirrors ``server.app.CAPABILITY_UNAVAILABLE_STATUS``. Duplicated rather than
#: imported to keep the import edge one-way: ``app`` includes these routers.
CAPABILITY_UNAVAILABLE_STATUS = 501

#: A well-formed spawn the adapter genuinely cannot honour *right now* (§2.1):
#: 409 rather than 501, because the reason is transient — despawn something and
#: the same request succeeds — unlike a missing capability.
TRAFFIC_AT_CAPACITY_STATUS = 409

#: Traffic push rate: 2 Hz, not the aircraft's 4 Hz — traffic is background
#: picture, not a control loop (§2, D10).
TRAFFIC_STREAM_INTERVAL_S = 0.5

#: The wire shape of one ``WS /ws/traffic`` frame: the full contact list,
#: replaced wholesale by the client on every frame.
_CONTACT_LIST = TypeAdapter(tuple[TrafficContact, ...])

#: No prefix, deliberately: the REST surface lives under ``/api/traffic`` but
#: the WebSocket is ``/ws/traffic`` (mirroring ``/ws/state``), and a router
#: prefix would apply to both. The router still owns the WS route (D10).
router = APIRouter(tags=["traffic"])


# ---------------------------------------------------------------------------
# Envelopes (§3.5)
# ---------------------------------------------------------------------------


class TrafficStatus(BaseModel):
    """``GET /api/traffic/status`` — every live contact the adapter reports."""

    adapter: str = Field(description="Name of the active adapter.")
    contacts: tuple[TrafficContact, ...] = Field(description="Every live traffic entity.")
    max_contacts: int | None = Field(
        default=None,
        description="Adapter-advertised capacity (D6), None when unknown/unbounded.",
    )


class TrafficSpawnResult(BaseModel):
    """``POST /api/traffic/spawn`` — one contact per track the request resolved into."""

    contacts: tuple[TrafficContact, ...] = Field(
        description="One per track spawned; more than one only for approach_sequence."
    )


# ---------------------------------------------------------------------------
# Capability gating (§2.1)
# ---------------------------------------------------------------------------


def _require_spawn_capability(adapter: SimAdapter) -> None:
    """Refuse a write up front when the adapter has not declared traffic support.

    Reads are never gated (§2.1): only ``/spawn``, ``DELETE /{traffic_id}`` and
    ``/clear`` call this.
    """
    if not adapter.capabilities.can_spawn_traffic:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare can_spawn_traffic, so traffic cannot be spawned.",
        )


async def _current_status(adapter: SimAdapter) -> TrafficStatus:
    """The full contact list, read back from the adapter — never from a ledger here.

    ``max_contacts`` is ``None`` for every adapter today: capacity is
    adapter-owned (D6) and the five-method ``SimAdapter`` contract carries no
    way to *advertise* it — only :class:`~core.traffic.TrafficCapacityExceeded`
    states the number, at the moment it is exceeded. ``None`` honestly means
    "unknown" until the contract grows an advertisement, which is a shared-
    foundation change this router must not smuggle in.
    """
    return TrafficStatus(adapter=adapter.name, contacts=await adapter.get_traffic_contacts())


# ---------------------------------------------------------------------------
# Resolution (§6.3)
# ---------------------------------------------------------------------------


def _runway(navdata: NavdataProvider, icao: str, ident: str) -> Runway:
    """The named runway, or the 404 ``position_routes`` already uses for one that is not there."""
    runway = navdata.get_runway(icao, ident)
    if runway is None:
        name = f"{icao.upper()} {ident.upper()}"
        raise HTTPException(
            status_code=404,
            detail=f"Runway {name!r} is not in the current navdata index.",
        )
    return runway


async def _resolve_spawn_requests(
    request: TrafficSpawnRequest, *, adapter: SimAdapter, navdata: NavdataProvider
) -> tuple[TrafficTrack, ...]:
    """Turn an instructor's intent into concrete, timed tracks (§6.3).

    The TCAS and incursion shapes read the user aircraft's state exactly once,
    here (D8). The runway lookup is blocking navdata work (SQLite, possibly a
    lazy CIFP parse) and runs off the event loop, the ``position_routes``
    precedent — run inline it would stall the ``/ws/state`` telemetry push.

    ``core.traffic``'s builders raise :class:`ValueError` when a well-formed
    request cannot be honoured from the data they were handed — a runway
    incursion timed against a stationary aircraft has no defensible crossing
    time. That is a 422 with the builder's own sentence, not a 500, exactly the
    posture ``position_routes._resolve`` takes for ``core.geodesy``.
    """
    try:
        return await _resolve_tracks(request, adapter=adapter, navdata=navdata)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _resolve_tracks(
    request: TrafficSpawnRequest, *, adapter: SimAdapter, navdata: NavdataProvider
) -> tuple[TrafficTrack, ...]:
    if isinstance(request, TcasConflictSpawnRequest):
        state = await adapter.get_aircraft_state()
        return (
            tcas_conflict_track(
                state,
                severity=request.severity,
                relative_bearing_deg=request.relative_bearing_deg,
                miss_side=request.miss_side,
                vertical_offset=request.vertical_offset,
                closure_ias_kt=request.closure_ias_kt,
                kind=request.kind,
                callsign=request.callsign,
            ),
        )

    if isinstance(request, RunwayIncursionSpawnRequest):
        runway = await run_in_threadpool(
            _runway, navdata, request.airport_icao, request.runway_ident
        )
        state = await adapter.get_aircraft_state()
        return (
            runway_incursion_track(
                runway,
                state,
                cross_at_along_track_nm=request.cross_at_along_track_nm,
                lead_time_before_user_arrival_s=request.lead_time_before_user_arrival_s,
                from_side=request.from_side,
                vehicle_speed_kt=request.vehicle_speed_kt,
                kind=request.kind,
                callsign=request.callsign,
            ),
        )

    if isinstance(request, ApproachSequenceSpawnRequest):
        runway = await run_in_threadpool(
            _runway, navdata, request.airport_icao, request.runway_ident
        )
        return approach_sequence_tracks(
            runway,
            distances_nm=request.distances_nm,
            ias_kt=request.ias_kt,
            category=request.category,
            kind=request.kind,
            callsign_prefix=request.callsign_prefix,
        )

    if isinstance(request, TaxiTrafficSpawnRequest):
        if request.speed_kt is None:
            return (
                taxi_traffic_track(request.route, kind=request.kind, callsign=request.callsign),
            )
        return (
            taxi_traffic_track(
                request.route,
                speed_kt=request.speed_kt,
                kind=request.kind,
                callsign=request.callsign,
            ),
        )

    # The union is closed and discriminated: four branches eliminated leaves
    # exactly the custom escape hatch, and its track is already validated.
    return (request.track,)


# ---------------------------------------------------------------------------
# Endpoints (§2)
# ---------------------------------------------------------------------------


@router.get("/api/traffic/status", response_model=TrafficStatus)
async def get_status() -> TrafficStatus:
    """Every live contact. Capability-free: no traffic support reads as no traffic."""
    return await _current_status(get_adapter())


@router.post("/api/traffic/spawn", response_model=TrafficSpawnResult)
async def spawn_traffic(request: TrafficSpawnRequest) -> TrafficSpawnResult:
    """Resolve a spawn request into tracks and spawn each. Not idempotent — twice is two.

    A multi-track ``approach_sequence`` is spawned sequentially, one awaited
    ``spawn_traffic`` per track. A failure partway through leaves the
    already-spawned entities spawned — no partial-failure rollback (§6.3), the
    same posture the scenario engine takes for its own multi-step run; ``/clear``
    is the one-tap way back.
    """
    adapter = get_adapter()
    _require_spawn_capability(adapter)
    tracks = await _resolve_spawn_requests(request, adapter=adapter, navdata=get_navdata())
    contacts: list[TrafficContact] = []
    for track in tracks:
        try:
            contacts.append(await adapter.spawn_traffic(track))
        except TrafficCapacityExceeded as exc:
            raise HTTPException(status_code=TRAFFIC_AT_CAPACITY_STATUS, detail=str(exc)) from exc
        except CapabilityNotSupported as exc:  # defence in depth; gated above
            raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return TrafficSpawnResult(contacts=tuple(contacts))


@router.delete("/api/traffic/{traffic_id}", response_model=TrafficStatus)
async def despawn_traffic(traffic_id: str) -> TrafficStatus:
    """Despawn one entity. Idempotent: an unknown or already-gone id is a no-op, 200 either way.

    A client racing a ``despawn_after_s`` auto-clear must never see an error for
    something it did nothing wrong to ask for (§2).
    """
    adapter = get_adapter()
    _require_spawn_capability(adapter)
    try:
        await adapter.despawn_traffic(traffic_id)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return await _current_status(adapter)


@router.post("/api/traffic/clear", response_model=TrafficStatus)
async def clear_all_traffic() -> TrafficStatus:
    """Despawn every entity the adapter is tracking. Idempotent — the one-tap reset."""
    adapter = get_adapter()
    _require_spawn_capability(adapter)
    try:
        await adapter.clear_all_traffic()
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return await _current_status(adapter)


@router.websocket("/ws/traffic")
async def traffic_socket(websocket: WebSocket) -> None:
    """Push the full contact list at 2 Hz until the client goes away.

    Never gated (§2.1): an adapter without traffic support streams ``[]``
    forever — ``stream_traffic`` is capability-free by contract — so the
    Instructor Map iterates unconditionally, exactly as it does ``/ws/state``.
    """
    await websocket.accept()
    adapter = get_adapter()
    try:
        async for contacts in adapter.stream_traffic(TRAFFIC_STREAM_INTERVAL_S):
            await websocket.send_text(_CONTACT_LIST.dump_json(contacts).decode())
    except WebSocketDisconnect:
        logger.debug("Traffic WebSocket client disconnected")
    except Exception:
        logger.exception("Traffic stream failed; closing the WebSocket")
        with suppress(Exception):
            await websocket.close(code=1011)
