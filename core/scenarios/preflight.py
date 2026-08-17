"""The capability pre-flight check — the whole mechanism behind "never
attempted halfway through" (roadmap Phase 2, exit criterion 4).

Per ``docs/designs/scenario-generator.md`` §6.2, D10: capability-only, never a
navdata check. Pure: ``(document, Capabilities)`` in, flags out. No adapter
instance, no I/O — the same posture as ``core.weather.presets.resolve_preset``
and ``core.failure_scheduler``: ``core/`` never holds a ``SimAdapter`` (D6).
"""

from __future__ import annotations

from core.models import AircraftSetup
from core.scenarios.models import ScenarioDocument
from core.sim_adapter import Capabilities

__all__ = ["missing_capabilities", "setup_capability_requirements"]

_AUTOPILOT_SETUP_FIELDS = frozenset(
    {
        "autopilot_master",
        "flight_director",
        "autopilot_nav",
        "autopilot_app",
        "autopilot_hdg",
        "target_altitude_ft",
        "target_ias_kt",
        "target_heading_deg",
        "target_vertical_speed_fpm",
    }
)
_FUEL_PAYLOAD_SETUP_FIELDS = frozenset({"gross_weight_kg", "fuel_kg"})


def setup_capability_requirements(setup: AircraftSetup) -> frozenset[str]:
    """Which Capabilities flags a non-empty AircraftSetup needs, mirroring
    apply_setup's own per-field gating (SimAdapter.apply_setup docstring):
    can_set_aircraft_state always, plus can_control_autopilot and/or
    can_set_fuel_payload when the corresponding fields are populated."""
    set_fields = setup.model_dump(exclude_none=True).keys()
    requirements = {"can_set_aircraft_state"}
    if set_fields & _AUTOPILOT_SETUP_FIELDS:
        requirements.add("can_control_autopilot")
    if set_fields & _FUEL_PAYLOAD_SETUP_FIELDS:
        requirements.add("can_set_fuel_payload")
    return frozenset(requirements)


def missing_capabilities(
    document: ScenarioDocument,
    capabilities: Capabilities,
) -> tuple[str, ...]:
    """Which capability flags this scenario needs but the adapter has not
    declared, in a stable order (weather, aircraft_state, position, failures,
    traffic). Pure: (document, Capabilities) in, flags out. No adapter
    instance, no I/O — the same posture as core.weather.presets.resolve_preset
    and core.failure_scheduler: core never holds a SimAdapter (D6)."""
    required: list[str] = []

    if document.weather is not None:
        required.append("can_set_weather")

    if document.aircraft_state is not None:
        # setup_capability_requirements() returns a frozenset — order is not
        # guaranteed, so it is walked in the fixed order the flags are checked
        # everywhere else in this function, rather than iterated directly.
        state_requirements = setup_capability_requirements(document.aircraft_state)
        for flag in ("can_set_aircraft_state", "can_control_autopilot", "can_set_fuel_payload"):
            if flag in state_requirements:
                required.append(flag)

    if document.position is not None:
        # A position block always carries at least a placement's own to_setup()
        # non-empty (speed, if nothing else) — evaluated conservatively as
        # {"can_set_aircraft_state"} here, mirroring
        # server/position_routes.py's own
        # `if setup.model_dump(exclude_none=True): _require_capability(...)`.
        required.append("can_set_position")
        required.append("can_set_aircraft_state")

    if document.failures is not None:
        required.append("can_inject_failures")

    if document.traffic is not None:
        required.append("can_spawn_traffic")

    missing: list[str] = []
    seen: set[str] = set()
    for flag in required:
        if flag in seen:
            continue
        seen.add(flag)
        if not bool(getattr(capabilities, flag, False)):
            missing.append(flag)
    return tuple(missing)
