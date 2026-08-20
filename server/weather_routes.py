"""``/api/weather/*`` — read the commanded weather, stage a preset or a setup, apply it.

**Two POSTs, one request shape** (weather-manager.md D7). ``preview`` resolves a
:class:`~core.weather.models.WeatherRequest` — a preset, a sparse setup, or a
preset with an overlay — against navdata and returns the exact
:class:`~core.weather.models.WeatherSetup` that *would* be written; it touches
no simulator. ``apply`` re-resolves from scratch and writes: the resolution is
a pure function of ``(navdata, request)``, so a client can never hand the
server a pre-resolved preset and call it staged (the Position panel's D2/D3
staging shape, unchanged).

``core.weather.presets.resolve_request`` does all the arithmetic; this module's
only job is to look the navdata context up — a runway's true bearing, an
airport's field elevation — and to turn what it finds (or does not find) into
the right HTTP status: 422 when the data cannot answer the request, 404 when
the named airport/runway is absent, 503 when the navdata index itself is
unavailable and the request actually needed it, 501 when the adapter does not
declare ``can_set_weather``. See docs/designs/weather-manager.md §2.2 for the
full table.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from core.navdata.provider import NavdataProvider
from core.sim_adapter import CapabilityNotSupported, WeatherRejected
from core.weather.models import WeatherPresetId, WeatherRequest, WeatherSetup, WeatherState
from core.weather.presets import WEATHER_PRESETS, resolve_request
from server._shared import _require_capability
from server.constants import CAPABILITY_UNAVAILABLE_STATUS
from server.deps import get_adapter, get_navdata

__all__ = [
    "CAPABILITY_UNAVAILABLE_STATUS",
    "UNRESOLVABLE_STATUS",
    "WeatherApplyResult",
    "WeatherManifest",
    "WeatherPresetInfo",
    "WeatherPreview",
    "router",
]

#: A request whose data cannot answer it — a preset needing a runway or a
#: field elevation it was not given. Mirrors
#: ``server.position_routes.UNPOSITIONABLE_STATUS``: the request is
#: well-formed, the *resolution* has nothing to resolve it against.
UNRESOLVABLE_STATUS = 422

router = APIRouter(prefix="/api/weather", tags=["weather"])


# ---------------------------------------------------------------------------
# Response envelopes — HTTP furniture only (weather-manager.md D6: the
# request model itself lives in core.weather.models, not here).
# ---------------------------------------------------------------------------


class WeatherPreview(BaseModel):
    """What ``apply`` *would* write. Computed without touching the simulator."""

    request: WeatherRequest
    setup: WeatherSetup = Field(description="Resolved and merged: exactly what apply would write.")
    notes: tuple[str, ...] = Field(
        default=(),
        description=(
            "Provenance sentences — where each resolved number came from, and which override "
            "displaced a preset value. Rendered verbatim by the UI, never re-derived."
        ),
    )


class WeatherApplyResult(BaseModel):
    """What actually happened."""

    applied: WeatherSetup = Field(description="Exactly the setup that was written.")
    state: WeatherState = Field(description="The read-back — the honest verdict.")
    notes: tuple[str, ...] = ()


class WeatherPresetInfo(BaseModel):
    """One catalogue entry, as the manifest publishes it."""

    id: WeatherPresetId
    label: str
    description: str
    requires_runway: bool
    requires_airport: bool


class WeatherManifest(BaseModel):
    """Supported-or-not with a reason, plus the preset catalogue.

    This manager's ``GET /api/aircraft/controls``: the single place the panel
    learns what it may offer. Always 200 — capability flags are static and the
    preset catalogue is ``core/`` data, so nothing here touches navdata or the
    simulator.
    """

    adapter: str
    supported: bool
    reason: str | None = Field(default=None, description="Why unsupported. None when supported.")
    presets: list[WeatherPresetInfo]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_context(
    provider: NavdataProvider, request: WeatherRequest
) -> tuple[float | None, float | None]:
    """The runway bearing / field elevation the request names.

    Returns ``(None, None)`` for a request that names no airport at all — it
    never touches the provider and can therefore never raise
    :class:`~core.navdata.provider.NavdataUnavailable` (weather-manager.md
    §2.2: "a request with no airport context never touches navdata").
    """
    if request.airport_icao is None:
        return None, None

    airport = provider.get_airport(request.airport_icao)
    if airport is None:
        raise HTTPException(
            status_code=404,
            detail=f"Airport {request.airport_icao.upper()!r} is not in the navigation index.",
        )
    field_elevation_ft = airport.elevation_ft

    runway_true_bearing_deg: float | None = None
    if request.runway_ident is not None:
        runway = provider.get_runway(request.airport_icao, request.runway_ident)
        if runway is None:
            raise HTTPException(
                status_code=404,
                detail=f"Runway {request.runway_ident.upper()} is not published at "
                f"{request.airport_icao.upper()}.",
            )
        runway_true_bearing_deg = runway.true_bearing_deg

    return runway_true_bearing_deg, field_elevation_ft


def _resolve(
    provider: NavdataProvider, request: WeatherRequest
) -> tuple[WeatherSetup, tuple[str, ...]]:
    """Resolve one request into a setup and its provenance notes, or raise 404/422.

    ``core.weather.presets.resolve_request`` raises :class:`ValueError` when
    the preset needs context the request did not carry — that is a 422 with
    the resolver's own sentence, not a 500: the request is well formed and the
    *data* cannot answer it (mirrors ``position_routes._resolve``).
    """
    runway_true_bearing_deg, field_elevation_ft = _resolve_context(provider, request)
    try:
        return resolve_request(
            request,
            runway_true_bearing_deg=runway_true_bearing_deg,
            field_elevation_ft=field_elevation_ft,
        )
    except ValueError as exc:
        raise HTTPException(status_code=UNRESOLVABLE_STATUS, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=WeatherState)
async def get_weather() -> WeatherState:
    """The commanded weather, read from the adapter."""
    adapter = get_adapter()
    _require_capability(adapter, "can_set_weather", "report the commanded weather")
    try:
        return await adapter.get_weather()
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    except WeatherRejected as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/manifest", response_model=WeatherManifest)
def get_weather_manifest() -> WeatherManifest:
    """Supported-or-not with a reason, plus the seven presets and their requirements."""
    adapter = get_adapter()
    supported = adapter.capabilities.can_set_weather
    reason = (
        None if supported else f"The {adapter.name!r} adapter does not declare can_set_weather."
    )
    presets = [
        WeatherPresetInfo(
            id=preset.id,
            label=preset.label,
            description=preset.description,
            requires_runway=preset.requires_runway,
            requires_airport=preset.requires_airport,
        )
        for preset in WEATHER_PRESETS.values()
    ]
    return WeatherManifest(
        adapter=adapter.name, supported=supported, reason=reason, presets=presets
    )


# ``def``, not ``async def`` — everything here is a navdata query and
# arithmetic, exactly the reasoning of ``position_routes.preview_placement``.
# It never awaits the simulator, and that is the point: staging a weather
# instruction needs no adapter at all.
@router.post("/preview", response_model=WeatherPreview)
def preview_weather(request: WeatherRequest) -> WeatherPreview:
    """Resolve a weather request without moving anything. Writes nothing, reads no adapter."""
    setup, notes = _resolve(get_navdata(), request)
    return WeatherPreview(request=request, setup=setup, notes=notes)


@router.post("/apply", response_model=WeatherApplyResult)
async def apply_weather(request: WeatherRequest) -> WeatherApplyResult:
    """Resolve, write, read back. See the module docstring for why apply re-resolves."""
    adapter = get_adapter()
    _require_capability(adapter, "can_set_weather", "control the weather")

    # Off the event loop, on purpose — the same blocking navdata work
    # ``preview`` does, run inline here would stall the loop that also serves
    # ``/ws/state`` (mirrors ``position_routes.apply_placement``).
    setup, notes = await run_in_threadpool(_resolve, get_navdata(), request)

    try:
        await adapter.set_weather(setup)
        state = await adapter.get_weather()
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    except WeatherRejected as exc:
        # The simulator, not the request, is at fault — it would not switch to
        # (or stay in) manual weather mode. 502: we are a gateway to it.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return WeatherApplyResult(applied=setup, state=state, notes=notes)
