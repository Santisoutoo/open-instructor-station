"""``GET /api/health``, ``/api/capabilities``, ``/api/state``, the Aircraft
Control panel's ``/api/aircraft/*``, and ``WS /ws/state``.

Split out of ``server/app.py`` (issue tracked in the modularization pass):
these six endpoints are the one part of the surface with no manager of its
own, so they get this catch-all router instead of a ``prefix=`` — the paths
themselves have nothing in common beyond not belonging to another module.

The Aircraft Control panel's own response models and helpers
(``AircraftControlId``, ``_CONTROL_FIELDS``, ``_build_manifest``,
``_blocked_reasons``, ...) stay in :mod:`server.app` rather than moving here
with the endpoints: ``tests/server/test_app.py`` patches
``server.app._CONTROL_FIELDS`` directly, and importing the functions that
close over it (rather than the mapping itself) keeps that patch effective —
a function looks its globals up in the module that *defines* it, not the one
that imports it.
"""

from __future__ import annotations

import logging
from contextlib import suppress

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from core.models import AircraftSetup, AircraftState
from core.sim_adapter import Capabilities, CapabilityNotSupported
from server.app import (
    AircraftControlManifest,
    AircraftSetupResult,
    HealthResponse,
    _blocked_reasons,
    _build_manifest,
)
from server.constants import CAPABILITY_UNAVAILABLE_STATUS
from server.constants import POLL_INTERVAL_S as STATE_STREAM_INTERVAL_S
from server.deps import get_adapter

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/health", tags=["system"], response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness plus which simulator we are talking to."""
    adapter = get_adapter()
    return HealthResponse(
        status="ok",
        adapter=adapter.name,
        connected=adapter.is_connected,
    )


@router.get("/api/capabilities", tags=["system"], response_model=Capabilities)
async def capabilities() -> Capabilities:
    """What the active adapter supports. The UI disables the rest."""
    return get_adapter().capabilities


@router.get("/api/state", tags=["aircraft"], response_model=AircraftState)
async def state() -> AircraftState:
    """One snapshot of the user aircraft."""
    return await get_adapter().get_aircraft_state()


@router.get(
    "/api/aircraft/controls",
    tags=["aircraft"],
    response_model=AircraftControlManifest,
)
async def aircraft_controls() -> AircraftControlManifest:
    """Which Aircraft Control panel controls are writable, and why the rest are not.

    The panel renders every control in this list. Entries with
    ``supported = false`` render disabled, showing ``reason`` — the UI never
    calls an endpoint the adapter cannot honour and never catches a failure
    it could have prevented.
    """
    return _build_manifest(get_adapter())


@router.post(
    "/api/aircraft/setup",
    tags=["aircraft"],
    response_model=AircraftSetupResult,
)
async def apply_aircraft_setup(setup: AircraftSetup) -> AircraftSetupResult:
    """Apply every field of ``setup`` that is set, leaving the rest untouched.

    Idempotent: the body states target values, not deltas, so replaying it is
    harmless. Any field whose control is unsupported is refused as a whole
    with ``501`` and a stated reason rather than partially applied.
    """
    adapter = get_adapter()
    requested = set(setup.model_dump(exclude_none=True))
    blocked = _blocked_reasons(adapter, requested)
    if blocked:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail="Unavailable on this adapter — " + " ".join(blocked),
        )
    try:
        await adapter.apply_setup(setup)
    except CapabilityNotSupported as exc:
        # Defence in depth: the manifest should already have disabled this.
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return AircraftSetupResult(applied=setup, state=await adapter.get_aircraft_state())


@router.websocket("/ws/state")
async def state_socket(websocket: WebSocket) -> None:
    """Push the aircraft state at ~4 Hz until the client goes away."""
    await websocket.accept()
    adapter = get_adapter()
    try:
        async for aircraft_state in adapter.stream_state(STATE_STREAM_INTERVAL_S):
            await websocket.send_text(aircraft_state.model_dump_json())
    except WebSocketDisconnect:
        logger.debug("State WebSocket client disconnected")
    except Exception:
        logger.exception("State stream failed; closing the WebSocket")
        with suppress(Exception):
            await websocket.close(code=1011)
