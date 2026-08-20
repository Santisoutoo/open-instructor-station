"""Small pieces of logic reimplemented near-identically across ``server/*_routes.py``.

Leading underscore, matching this codebase's convention for a module that is
not itself a route module (no ``router = APIRouter()``) — it exists to be
imported, never included in ``server.app.create_app()``.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from core.navdata.provider import NavdataProvider
from core.sim_adapter import SimAdapter
from core.weather.models import WeatherRequest, WeatherSetup, WeatherState
from server.constants import CAPABILITY_UNAVAILABLE_STATUS

__all__ = ["_require_capability", "_resolve_apply_and_readback_weather", "_weather_context"]


def _require_capability(adapter: SimAdapter, flag: str, what: str) -> None:
    """Refuse up front when the adapter has not declared what this needs."""
    if not bool(getattr(adapter.capabilities, flag, False)):
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare {flag}, so it cannot {what}.",
        )


def _weather_context(
    provider: NavdataProvider, request: WeatherRequest
) -> tuple[float | None, float | None]:
    """The runway bearing / field elevation a weather request names, or ``(None, None)``.

    Raises :class:`ValueError` — never :class:`~fastapi.HTTPException` — so it
    is callable from both an HTTP request (``server.weather_routes._resolve_context``
    wraps it into a 404) and a scenario run
    (``server.scenario_engine``, which has no HTTP request to answer and
    already only recognises :class:`ValueError` as a step failure, §6.3).

    Returns ``(None, None)`` for a request that names no airport at all — it
    never touches the provider and can therefore never raise
    :class:`~core.navdata.provider.NavdataUnavailable` (weather-manager.md
    §2.2: "a request with no airport context never touches navdata").
    """
    if request.airport_icao is None:
        return None, None

    airport = provider.get_airport(request.airport_icao)
    if airport is None:
        raise ValueError(
            f"Airport {request.airport_icao.upper()!r} is not in the navigation index."
        )
    field_elevation_ft = airport.elevation_ft

    runway_true_bearing_deg: float | None = None
    if request.runway_ident is not None:
        runway = provider.get_runway(request.airport_icao, request.runway_ident)
        if runway is None:
            raise ValueError(
                f"Runway {request.runway_ident.upper()} is not published at "
                f"{request.airport_icao.upper()}."
            )
        runway_true_bearing_deg = runway.true_bearing_deg

    return runway_true_bearing_deg, field_elevation_ft


async def _resolve_apply_and_readback_weather(
    resolve: Callable[[NavdataProvider, WeatherRequest], tuple[WeatherSetup, tuple[str, ...]]],
    navdata: NavdataProvider,
    request: WeatherRequest,
    *,
    adapter: SimAdapter,
) -> tuple[WeatherSetup, WeatherState, tuple[str, ...]]:
    """Resolve off the event loop, write, read back. Sequencing only.

    Shared by ``server.weather_routes.apply_weather`` and
    ``server.profile_routes._apply_weather`` — the two call sites whose
    sequence is genuinely identical. **Not** by
    ``server.scenario_engine._run_weather_step``: that step never reads the
    weather back after writing it, which is a real difference in sequence,
    not merely in how a result or exception gets reported — so it keeps its
    own two-step ``resolve`` -> ``set_weather``.

    ``resolve`` is passed in rather than imported, so this stays free of
    which caller's own resolver function it is (``weather_routes._resolve``,
    reused by ``profile_routes`` under its own alias) and free of a
    ``server._shared`` <-> ``server.weather_routes`` import cycle.

    Raises whatever ``resolve``/``adapter.set_weather``/``adapter.get_weather``
    raise, uncaught: each caller keeps translating the result or a raised
    exception to its own type (``HTTPException`` / a ``ProfileWeatherOutcome``)
    — deliberately not unified here.
    """
    setup, notes = await run_in_threadpool(resolve, navdata, request)
    await adapter.set_weather(setup)
    state = await adapter.get_weather()
    return setup, state, notes
