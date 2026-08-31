"""``/api/pushback/*`` — push the aircraft back from the gate: straight, or
through an arc that ends with the nose rotated by a chosen angle.

The whole manager is three endpoints and no arithmetic of its own. Every number
comes from :func:`core.pushback.pushback_target`, the one pure function the
adapters' ``pushback()`` also calls (``docs/designs/pushback-manager.md`` D7):
preview and execute can therefore only disagree if the aircraft moved between
the two calls, never because the router re-derived the geometry a second way.

Two refusals, deliberately different (§2.1):

* **501** — the adapter does not declare ``can_pushback``. A *capability*
  answer: this simulator has no pushback at all, and the panel should have
  been disabled long before the request was made.
* **409** — the aircraft is airborne (:class:`core.pushback.PushbackNotOnGround`).
  A *precondition*, not a capability (D8): the adapter can push back perfectly
  well; this aircraft, right now, cannot be pushed. 501 would tell the panel to
  disable itself forever over a condition that clears the moment the wheels
  touch.

Bad numbers — ``distance_m``/``angle_deg`` out of bounds, or an ``angle_deg``
that contradicts ``direction`` — are 422s raised by
:class:`~core.pushback.PushbackRequest`'s own field constraints and
``model_validator``, so the same rule applies whether the request came from the
panel or (later) a scenario step (D9: the model lives in ``core/``, not here).

**No 503, no 404.** This manager reads no ``NavdataProvider`` and names no
airport: a pushback is defined entirely relative to where the aircraft is now.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.models import AircraftState, GeoPosition
from core.pushback import (
    PUSHBACK_MAX_ANGLE_DEG,
    PUSHBACK_MAX_DISTANCE_M,
    PushbackManifest,
    PushbackNotOnGround,
    PushbackPreview,
    PushbackRequest,
    PushbackResult,
    PushbackTarget,
    pushback_target,
    require_on_ground,
)
from core.sim_adapter import CapabilityNotSupported, SimAdapter
from server.deps import get_adapter

__all__ = [
    "CAPABILITY_UNAVAILABLE_STATUS",
    "NOT_ON_GROUND_STATUS",
    "router",
]

#: Mirrors ``server.app.CAPABILITY_UNAVAILABLE_STATUS``. Duplicated rather than
#: imported to keep the import edge one-way: ``app`` includes these routers.
CAPABILITY_UNAVAILABLE_STATUS = 501

#: The aircraft is airborne. A state precondition, not a capability failure
#: (D8) — 409 Conflict: the request is well-formed and the adapter implements
#: it, but the aircraft's current state conflicts with it.
NOT_ON_GROUND_STATUS = 409

router = APIRouter(prefix="/api/pushback", tags=["pushback"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_capability(adapter: SimAdapter) -> None:
    """Refuse up front when the adapter has not declared ``can_pushback``."""
    if not adapter.capabilities.can_pushback:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare can_pushback, so it cannot push the aircraft back.",
        )


def _position_of(state: AircraftState) -> GeoPosition:
    """The positional part of a live state."""
    return GeoPosition(
        latitude=state.latitude,
        longitude=state.longitude,
        altitude_ft=state.altitude_ft,
    )


def _resolve_or_409(state: AircraftState, request: PushbackRequest) -> PushbackTarget:
    """Resolve ``request`` from ``state``, refusing an airborne aircraft with 409.

    The precondition is enforced here — in the route, before the adapter is
    ever called — *and* again inside every adapter's ``pushback()`` (D8,
    defence in depth). Preview enforces it too: a preview that happily draws a
    path execute would refuse is a lie, and this is a state precondition, not
    the capability gate D6 keeps off ``/preview``.
    """
    try:
        require_on_ground(state)
    except PushbackNotOnGround as exc:
        raise HTTPException(status_code=NOT_ON_GROUND_STATUS, detail=str(exc)) from exc
    return pushback_target(state, request)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/manifest", response_model=PushbackManifest)
def get_pushback_manifest() -> PushbackManifest:
    """Capability + reason, and the exact slider bounds.

    ``def``, not ``async def``: a capability-flag read and two module
    constants, never simulator I/O. The bounds are echoed so the panel's
    sliders never hold a second, drifting copy of
    :class:`~core.pushback.PushbackRequest`'s field constraints.
    """
    adapter = get_adapter()
    supported = adapter.capabilities.can_pushback
    reason = None if supported else f"The {adapter.name!r} adapter does not declare can_pushback."
    return PushbackManifest(
        adapter=adapter.name,
        supported=supported,
        reason=reason,
        max_distance_m=PUSHBACK_MAX_DISTANCE_M,
        max_angle_deg=PUSHBACK_MAX_ANGLE_DEG,
    )


@router.post("/preview", response_model=PushbackPreview)
async def preview_pushback(request: PushbackRequest) -> PushbackPreview:
    """Where the aircraft would end up, and the path it would take. Writes nothing.

    ``async def`` and not capability-gated (D6): the one adapter call is
    ``get_aircraft_state()``, which carries no capability on the protocol.
    Unlike the Weather and Position previews this one *must* read the
    simulator — a pushback is a relative manoeuvre, and without knowing where
    the aircraft is and which way it points there is no geometry to preview.
    """
    state = await get_adapter().get_aircraft_state()
    return PushbackPreview(
        request=request,
        current_position=_position_of(state),
        current_heading_deg=state.heading_deg,
        target=_resolve_or_409(state, request),
    )


@router.post("/execute", response_model=PushbackResult)
async def execute_pushback(request: PushbackRequest) -> PushbackResult:
    """Push the aircraft back, then read the result back.

    **Not idempotent, on purpose.** ``request`` states a manoeuvre relative to
    wherever the aircraft is now, not an absolute target, so replaying it
    pushes back a second time — the throttle-nudge shape, unlike every
    ``apply`` in this codebase. That is the manager's contract, pinned by the
    contract suite's ``test_pushback_is_idempotent_in_direction_only``.

    ``target`` is computed here from the state read a moment before the write;
    the adapter re-resolves from its own fresh read (D7). Both call the same
    pure function, so the two can differ only if the aircraft moved in
    between — untrue of a parked aircraft on a ramp. ``state`` is the
    read-back afterwards, which is the honest verdict on what happened.
    """
    adapter = get_adapter()
    _require_capability(adapter)

    target = _resolve_or_409(await adapter.get_aircraft_state(), request)

    try:
        await adapter.pushback(request)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    except PushbackNotOnGround as exc:
        # Defence in depth again: the route checked a moment ago, but the
        # adapter's own read is the one that decides, and an aircraft that
        # rolled off a slope in between is a 409, never a 500.
        raise HTTPException(status_code=NOT_ON_GROUND_STATUS, detail=str(exc)) from exc

    return PushbackResult(request=request, target=target, state=await adapter.get_aircraft_state())
