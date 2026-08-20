"""The FastAPI application.

Reads and writes are deliberately separated, exactly as the Aircraft Control
manager is specified: the live picture is pushed over ``WS /ws/state`` and every
write is an idempotent REST call.

Surface:

* ``GET  /api/health``, ``GET /api/capabilities``, ``GET /api/state``, the
  Aircraft Control panel's ``/api/aircraft/*`` and ``WS /ws/state`` — the one
  part of the surface with no manager of its own, registered in
  :mod:`server.system_routes`. Its response models and helpers
  (``AircraftControlId``, ``_CONTROL_FIELDS``, ``_build_manifest``, ...) stay
  in this module — see :mod:`server.system_routes`'s own docstring for why.
* ``/api/navdata/*`` and ``/api/position/*`` — the Position Manager, in
  :mod:`server.navdata_routes` and :mod:`server.position_routes`.
* ``/api/weather/*`` — the Weather Manager, in :mod:`server.weather_routes`.
* ``/api/fuel-payload/*`` — the Fuel & Payload Manager, in
  :mod:`server.fuel_payload_routes`.
* ``/api/failures/*`` — the Failures Manager, in :mod:`server.failure_routes`.
* ``/api/pushback/*`` — the Pushback Manager, in :mod:`server.pushback_routes`.
* ``/api/scenarios/*`` — the Flight Scenario Generator, in
  :mod:`server.scenario_routes`.
* ``/api/profiles/*`` — Training Profiles, in :mod:`server.profile_routes`.
* ``/api/geodesy/*`` — the Instructor Map's exact measurement, in
  :mod:`server.geodesy_routes`.
* ``/api/camera/*`` — the Camera Manager, in :mod:`server.camera_routes`.
* ``/api/traffic/*`` and ``WS /ws/traffic`` — the AI Traffic Manager, in
  :mod:`server.traffic_routes`.

The UI (built separately into ``ui/dist``) is served from ``/`` when it exists;
the server starts perfectly well without it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal, get_args

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.models import AircraftSetup, AircraftState
from core.navdata.provider import NavdataUnavailable
from core.sim_adapter import SimAdapter
from server import (
    camera_routes,
    failure_routes,
    fuel_payload_routes,
    geodesy_routes,
    navdata_routes,
    position_routes,
    profile_routes,
    pushback_routes,
    scenario_routes,
    traffic_routes,
    weather_routes,
)
from server.deps import get_adapter, load_airframe_info

__all__ = [
    "CONTROL_IDS",
    "UI_DIST",
    "AircraftControlId",
    "AircraftControlManifest",
    "AircraftControlSupport",
    "AircraftSetupResult",
    "HealthResponse",
    "create_app",
]

logger = logging.getLogger(__name__)

#: Where the separately-built frontend lands. Optional.
UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"

#: The Vite dev server. CORS is permissive because the station is a LAN tool,
#: not a public site.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


# ---------------------------------------------------------------------------
# The Aircraft Control panel's control catalogue
# ---------------------------------------------------------------------------

#: Every control the Aircraft Control panel offers. A ``Literal`` rather than a
#: bare ``str`` so the identifiers land in the OpenAPI schema as a closed union
#: and the generated TypeScript client can exhaustively switch on them.
AircraftControlId = Literal[
    # -- Configuration --
    "flaps",
    "speedbrake",
    "gear",
    "autobrake",
    "trim",
    "throttle",
    "lights",
    # -- Direct flight state --
    "altitude",
    "speed",
    "vertical_speed",
    "heading",
    # -- Autopilot --
    "autopilot_master",
    "autopilot_nav",
    "autopilot_app",
    "autopilot_hdg",
    "flight_director",
    "target_altitude",
    "target_speed",
    "target_heading",
    "target_vertical_speed",
]

#: Display order of :data:`AircraftControlId`, taken from the type itself so the
#: two can never drift apart.
CONTROL_IDS: tuple[AircraftControlId, ...] = get_args(AircraftControlId)

#: Capability assumed for an ``AircraftSetup`` field that no panel control owns
#: (the radios and the mass fields, written by the Position Manager).
DEFAULT_CAPABILITY = "can_set_aircraft_state"

#: control -> (the ``AircraftSetup`` field that writes it, the capability the
#: adapter must declare).
#:
#: The field name is looked up in ``AircraftSetup.model_fields`` at request time
#: rather than hard-asserted here: several of these fields do not exist yet
#: (trim, and the whole autopilot block). Those controls report themselves as
#: unsupported with a reason, and light up on their own the day ``core.models``
#: grows the field — no change needed in this file.
_CONTROL_FIELDS: Mapping[AircraftControlId, tuple[str, str]] = {
    "flaps": ("flaps_ratio", DEFAULT_CAPABILITY),
    "speedbrake": ("speedbrake_ratio", DEFAULT_CAPABILITY),
    "gear": ("gear_down", DEFAULT_CAPABILITY),
    "autobrake": ("autobrake_level", DEFAULT_CAPABILITY),
    "trim": ("elevator_trim_ratio", DEFAULT_CAPABILITY),
    "throttle": ("throttle_ratio", DEFAULT_CAPABILITY),
    "lights": ("lights", DEFAULT_CAPABILITY),
    "altitude": ("altitude_ft", DEFAULT_CAPABILITY),
    "speed": ("ias_kt", DEFAULT_CAPABILITY),
    "vertical_speed": ("vertical_speed_fpm", DEFAULT_CAPABILITY),
    "heading": ("heading_deg", DEFAULT_CAPABILITY),
    "autopilot_master": ("autopilot_master", "can_control_autopilot"),
    "autopilot_nav": ("autopilot_nav", "can_control_autopilot"),
    "autopilot_app": ("autopilot_app", "can_control_autopilot"),
    "autopilot_hdg": ("autopilot_hdg", "can_control_autopilot"),
    "flight_director": ("flight_director", "can_control_autopilot"),
    "target_altitude": ("target_altitude_ft", "can_control_autopilot"),
    "target_speed": ("target_ias_kt", "can_control_autopilot"),
    "target_heading": ("target_heading_deg", "can_control_autopilot"),
    "target_vertical_speed": ("target_vertical_speed_fpm", "can_control_autopilot"),
}


class HealthResponse(BaseModel):
    """``GET /api/health``.

    A declared model rather than a bare ``dict``: the UI client is generated from
    this schema, and an untyped dict generates as ``unknown`` on the TypeScript
    side, which is exactly the kind of hand-written patching CLAUDE.md forbids.
    """

    status: str = Field(description='Always "ok" when the process is answering.')
    adapter: str = Field(description="Name of the active adapter.")
    connected: bool = Field(description="True when the adapter's link to the simulator is up.")


class AircraftControlSupport(BaseModel):
    """Whether one panel control is writable right now — and why not, when it is not.

    This is hard rule 3 ("capabilities, not failures") made specific enough for a
    UI to act on: a raw capability flag says the adapter can drive an autopilot,
    it does not say the server has a field to carry the request. Both have to be
    true, and the panel needs to tell the instructor which one is missing.
    """

    control: AircraftControlId = Field(description="Panel control identifier.")
    setup_field: str = Field(description="The AircraftSetup field this control writes.")
    capability: str = Field(description="Capability flag the adapter must declare.")
    supported: bool = Field(description="True when the control may be written.")
    reason: str | None = Field(
        default=None, description="Why the control is disabled. None when supported."
    )


class AircraftControlManifest(BaseModel):
    """The full control catalogue, resolved against the active adapter."""

    adapter: str = Field(description="Name of the adapter the manifest was resolved against.")
    controls: list[AircraftControlSupport] = Field(description="One entry per panel control.")


class AircraftSetupResult(BaseModel):
    """The outcome of a write: what was asked for, and what the aircraft looks like now.

    ``applied`` is echoed back because :class:`~core.models.AircraftState` does
    not carry configuration — flaps, gear and lights are invisible in the live
    feed, so the panel would have nothing to reconcile them against.
    """

    applied: AircraftSetup = Field(description="Exactly the setup that was applied.")
    state: AircraftState = Field(description="The aircraft state after the write.")


def _control_support(control: AircraftControlId, adapter: SimAdapter) -> AircraftControlSupport:
    """Resolve one control against ``adapter``, with a human reason when it is disabled."""
    setup_field, capability = _CONTROL_FIELDS[control]
    declared = bool(getattr(adapter.capabilities, capability, False))
    modelled = setup_field in AircraftSetup.model_fields

    reason: str | None = None
    if not declared:
        reason = f"The {adapter.name!r} adapter does not declare {capability}."
    elif not modelled:
        reason = (
            f"Not wired yet: AircraftSetup has no {setup_field!r} field, so there is "
            f"no path from this control to the simulator."
        )

    return AircraftControlSupport(
        control=control,
        setup_field=setup_field,
        capability=capability,
        supported=reason is None,
        reason=reason,
    )


def _build_manifest(adapter: SimAdapter) -> AircraftControlManifest:
    """The whole catalogue, in display order, resolved against ``adapter``."""
    return AircraftControlManifest(
        adapter=adapter.name,
        controls=[_control_support(control, adapter) for control in CONTROL_IDS],
    )


def _blocked_reasons(adapter: SimAdapter, setup_fields: Iterable[str]) -> list[str]:
    """Why each of ``setup_fields`` cannot be written. Empty when the write is allowed."""
    owner = {field: control for control, (field, _) in _CONTROL_FIELDS.items()}
    reasons: list[str] = []
    for setup_field in sorted(setup_fields):
        control = owner.get(setup_field)
        if control is None:
            # Not a panel control (radios, mass): the generic write gate applies.
            if not bool(getattr(adapter.capabilities, DEFAULT_CAPABILITY, False)):
                reasons.append(
                    f"{setup_field}: the {adapter.name!r} adapter does not "
                    f"declare {DEFAULT_CAPABILITY}."
                )
            continue
        support = _control_support(control, adapter)
        if support.reason is not None:
            reasons.append(f"{setup_field}: {support.reason}")
    return reasons


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Connect the adapter on startup, disconnect on shutdown.

    A simulator that is not running must not stop the server from starting:
    the UI needs to come up and show "disconnected" rather than fail to load.
    """
    adapter: SimAdapter = get_adapter()
    try:
        await adapter.connect()
    except Exception:
        logger.exception("Adapter %r failed to connect at startup", adapter.name)
    else:
        # The one read of the loaded airframe (issue #82). Here and not in a
        # request handler, because the preview route is deliberately sync and
        # must never await the simulator — it reads the cache this fills. A
        # failure degrades to the all-None airframe (category B default) and
        # must not stop the server any more than a failed connect does.
        try:
            await load_airframe_info()
        except Exception:
            logger.exception("Could not read the loaded airframe from %r", adapter.name)
    try:
        yield
    finally:
        with suppress(Exception):
            await adapter.disconnect()


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="Open Instructor Station",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Deferred, not at module level: server.system_routes imports the Aircraft
    # Control models/helpers straight out of this module (so
    # tests/server/test_app.py's server.app._CONTROL_FIELDS patch stays
    # effective), and importing it here — after everything it needs is
    # already defined above — avoids the import cycle a module-level import
    # would create.
    from server import system_routes

    # The feature managers live in their own routers; this module stays the
    # shell. Registered before the UI mount, which claims "/".
    app.include_router(system_routes.router)
    app.include_router(geodesy_routes.router)
    app.include_router(navdata_routes.router)
    app.include_router(position_routes.router)
    app.include_router(weather_routes.router)
    app.include_router(fuel_payload_routes.router)
    app.include_router(failure_routes.router)
    app.include_router(pushback_routes.router)
    app.include_router(scenario_routes.router)
    app.include_router(profile_routes.router)
    app.include_router(camera_routes.router)
    app.include_router(traffic_routes.router)
    app.add_exception_handler(NavdataUnavailable, navdata_routes.navdata_unavailable_handler)

    _mount_ui(app)
    return app


def _mount_ui(app: FastAPI) -> None:
    """Serve ``ui/dist`` at ``/`` if it has been built, otherwise do nothing."""
    if not UI_DIST.is_dir():
        logger.info("No built UI at %s; serving the API only", UI_DIST)
        return
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
