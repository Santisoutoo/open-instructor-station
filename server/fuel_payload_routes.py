"""``/api/fuel-payload/*`` — mass and balance: presets, a tank/station editor,
stage-then-commit, envelope validation that refuses rather than silently
accepts.

**Both ``preview`` and ``apply`` require ``can_set_fuel_payload``** (D4 of
``docs/designs/fuel-payload.md``), unlike the sibling managers' capability-free
previews: mass-and-balance is a whole-aircraft computation, and there is no
sim-agnostic way to invent the rest of the aircraft's loadout without reading
it first. ``preview`` therefore reads the current loadout via
``adapter.get_loadout()`` and seeds the resolution from it.

**A verifiably out-of-envelope loadout is refused (422) by default, with an
explicit ``override_envelope`` escape hatch on ``apply``** (D8) — a stronger
stance than the zero-speed warning's "warn, never refuse", because here the
station genuinely can compute the answer.

**No 503.** This manager reads no ``NavdataProvider`` (D17 of the design) —
there is no code path that can raise ``NavdataUnavailable``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.fuel_payload.limits import (
    AIRCRAFT_MASS_LIMITS_TABLE,
    ResolvedMassLimits,
    resolve_mass_limits,
)
from core.fuel_payload.mass_and_balance import compute_mass_and_balance, resolve_request
from core.fuel_payload.models import (
    FUEL_PAYLOAD_PRESETS,
    FuelPayloadPresetId,
    FuelPayloadRequest,
    MassAndBalanceResult,
)
from core.models import AircraftSetup, AirframeInfo, AirframeMassLimits, Loadout, LoadoutState
from core.sim_adapter import CapabilityNotSupported, SimAdapter
from server.constants import CAPABILITY_UNAVAILABLE_STATUS
from server.deps import get_adapter, get_airframe_info

__all__ = [
    "ENVELOPE_VIOLATION_STATUS",
    "FuelPayloadApplyResult",
    "FuelPayloadManifest",
    "FuelPayloadPresetInfo",
    "FuelPayloadPreview",
    "FuelPayloadState",
    "router",
]

#: A resolved loadout that is verifiably outside the CG envelope, and the
#: instructor did not set ``override_envelope`` (D8). The request is
#: well-formed and the numbers are known — this is a refusal, not a data error
#: — but 422 is still the right family: the body as given cannot be honoured.
ENVELOPE_VIOLATION_STATUS = 422

router = APIRouter(prefix="/api/fuel-payload", tags=["fuel-payload"])


# ---------------------------------------------------------------------------
# HTTP furniture (§3.3) — request/response shapes that never leave this router
# ---------------------------------------------------------------------------


class FuelPayloadPresetInfo(BaseModel):
    """One catalogue entry, as the manifest lists it."""

    id: FuelPayloadPresetId
    label: str
    description: str


class FuelPayloadManifest(BaseModel):
    """``GET /manifest`` — this manager's ``GET /api/aircraft/controls``.

    Answers without touching the simulator or the navdata index: capability
    flags are static and ``AirframeInfo`` is the cache
    ``server.deps.load_airframe_info`` already populates at connect. Always
    200, always fast.
    """

    adapter: str
    supported: bool
    reason: str | None
    icao_type: str | None
    limits_source: Literal["adapter", "table", "unknown"]
    limits_note: str | None = Field(
        default=None, description="The table entry's disclaimer, when limits_source == 'table'."
    )
    limits: AirframeMassLimits | None = Field(
        default=None,
        description="The resolved mass/CG facts themselves -- empty weight, MTOW, tank/station "
        "capacities and arms, the CG envelope polygon -- so the panel can render MTOW and the "
        "envelope without a second round trip. None iff limits_source == 'unknown'.",
    )
    tank_count: int
    station_count: int
    presets: list[FuelPayloadPresetInfo]


class FuelPayloadState(BaseModel):
    """The current loadout plus its computed mass-and-balance."""

    loadout: LoadoutState
    mass_and_balance: MassAndBalanceResult


class FuelPayloadPreview(BaseModel):
    """What ``apply`` would produce. Writes nothing."""

    request: FuelPayloadRequest
    loadout: LoadoutState = Field(description="Fully resolved — exactly what apply would write.")
    mass_and_balance: MassAndBalanceResult
    notes: tuple[str, ...] = ()


class FuelPayloadApplyResult(BaseModel):
    """What actually happened. ``state`` is the read-back — the honest verdict."""

    applied: LoadoutState
    state: FuelPayloadState
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_capability(adapter: SimAdapter) -> None:
    """Refuse up front when the adapter has not declared ``can_set_fuel_payload``."""
    if not adapter.capabilities.can_set_fuel_payload:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare can_set_fuel_payload, so it cannot set fuel or payload.",
        )


def _no_capacities_detail(preset_id: FuelPayloadPresetId, airframe: AirframeInfo) -> str:
    """The 422 detail for a preset requested against an airframe with no known capacities."""
    named = f" for {airframe.icao_type!r}" if airframe.icao_type else ""
    return (
        f"The {preset_id!r} preset needs the airframe's known tank and station capacities; "
        f"none are published for this aircraft and no fallback table entry exists{named}."
    )


def _limits_note(
    airframe: AirframeInfo, limits_source: Literal["adapter", "table", "unknown"]
) -> str | None:
    """The table entry's disclaimer, when the resolved limits came from the table."""
    if limits_source != "table" or airframe.icao_type is None:
        return None
    entry = AIRCRAFT_MASS_LIMITS_TABLE.get(airframe.icao_type)
    return entry.source_note if entry is not None else None


async def _resolve_or_422(
    request: FuelPayloadRequest, adapter: SimAdapter
) -> tuple[LoadoutState, MassAndBalanceResult, tuple[str, ...], ResolvedMassLimits | None]:
    """Steps 2-4 of §2.1, shared by preview and apply.

    Reads the current loadout, resolves the mass/CG limits, and resolves
    ``request`` against both. Every way resolution can fail becomes a 422
    naming the reason, never a 500: the body is well-formed, the *data*
    cannot honour it (the same posture ``server.position_routes._resolve``
    already established for navdata lookups). Returns the resolved limits
    alongside the result so ``apply`` can reuse them for the read-back's
    recomputation instead of resolving twice.
    """
    current = await adapter.get_loadout()
    airframe = get_airframe_info()
    limits = resolve_mass_limits(airframe)
    if request.preset is not None and limits is None:
        raise HTTPException(status_code=422, detail=_no_capacities_detail(request.preset, airframe))
    try:
        resolved, result, notes = resolve_request(request, current=current, limits=limits)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return resolved, result, notes, limits


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/manifest", response_model=FuelPayloadManifest)
def get_manifest() -> FuelPayloadManifest:
    """Capability + reason, resolved mass limits and their provenance, the preset catalogue.

    ``def``, not ``async def``: everything here is a capability-flag check and
    a cached ``AirframeInfo`` read, never simulator I/O.
    """
    adapter = get_adapter()
    airframe = get_airframe_info()
    resolved = resolve_mass_limits(airframe)
    supported = adapter.capabilities.can_set_fuel_payload
    reason = (
        None
        if supported
        else f"The {adapter.name!r} adapter does not declare can_set_fuel_payload."
    )
    limits_source: Literal["adapter", "table", "unknown"] = (
        resolved.source if resolved is not None else "unknown"
    )
    return FuelPayloadManifest(
        adapter=adapter.name,
        supported=supported,
        reason=reason,
        icao_type=airframe.icao_type,
        limits_source=limits_source,
        limits_note=_limits_note(airframe, limits_source),
        limits=resolved.limits if resolved is not None else None,
        tank_count=len(resolved.limits.fuel_tank_capacities_kg) if resolved is not None else 0,
        station_count=(
            len(resolved.limits.payload_station_capacities_kg) if resolved is not None else 0
        ),
        presets=[
            FuelPayloadPresetInfo(id=preset.id, label=preset.label, description=preset.description)
            for preset in FUEL_PAYLOAD_PRESETS.values()
        ],
    )


@router.get("", response_model=FuelPayloadState)
async def get_fuel_payload() -> FuelPayloadState:
    """The current loadout plus its computed mass-and-balance."""
    adapter = get_adapter()
    _require_capability(adapter)
    loadout = await adapter.get_loadout()
    limits = resolve_mass_limits(get_airframe_info())
    return FuelPayloadState(
        loadout=loadout, mass_and_balance=compute_mass_and_balance(loadout, limits)
    )


@router.post("/preview", response_model=FuelPayloadPreview)
async def preview_fuel_payload(request: FuelPayloadRequest) -> FuelPayloadPreview:
    """Resolve ``request`` into the exact loadout and mass-and-balance ``apply`` would produce.

    Writes nothing: ``get_loadout()`` is read but ``apply_setup`` is never
    called.
    """
    adapter = get_adapter()
    _require_capability(adapter)
    resolved, result, notes, _limits = await _resolve_or_422(request, adapter)
    return FuelPayloadPreview(
        request=request, loadout=resolved, mass_and_balance=result, notes=notes
    )


@router.post("/apply", response_model=FuelPayloadApplyResult)
async def apply_fuel_payload(request: FuelPayloadRequest) -> FuelPayloadApplyResult:
    """Re-resolve, refuse if out of envelope and not overridden, write, read back.

    Idempotent: the body states an absolute target loadout, never a delta —
    replaying it writes the same numbers again.
    """
    adapter = get_adapter()
    _require_capability(adapter)
    resolved, result, notes, limits = await _resolve_or_422(request, adapter)

    if result.within_envelope is False and not request.override_envelope:
        raise HTTPException(
            status_code=ENVELOPE_VIOLATION_STATUS, detail="\n".join(result.violations)
        )

    try:
        await adapter.apply_setup(
            AircraftSetup(loadout=Loadout(tanks=resolved.tanks, stations=resolved.stations))
        )
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc

    # The read-back, the honest verdict — never the resolved value trusted
    # from resolve_request, exactly as get_weather()'s read-back is never the
    # setup that was sent (docs/designs/fuel-payload.md §2.1 step 7-8).
    state = await adapter.get_loadout()
    verified = compute_mass_and_balance(state, limits)
    return FuelPayloadApplyResult(
        applied=resolved,
        state=FuelPayloadState(loadout=state, mass_and_balance=verified),
        notes=notes,
    )
