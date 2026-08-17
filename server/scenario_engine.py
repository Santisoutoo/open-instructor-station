"""The scenario run engine — the sequence of *awaited* adapter calls.

Deliberately **not** ``core/`` (D6, ``docs/designs/scenario-generator.md``
§5, §6.3): loading, validating and the capability pre-flight check are pure
and live in :mod:`core.scenarios`, but *executing* a scenario means holding a
live :class:`~core.sim_adapter.SimAdapter`, which ``core/`` never does.

Module-owned singleton state, the same shape as the Failures Manager's
watcher (:mod:`server.failure_routes`): exactly one scenario runs at a time,
tracked in :data:`_current_run` and driven by the background task in
:data:`_current_task`.

**The pre-flight check is the whole mechanism behind "never attempted
halfway through" (roadmap Phase 2, exit criterion 4).**
:func:`start_run` computes :func:`core.scenarios.preflight.missing_capabilities`
and raises *before* creating any task when it is non-empty — nothing from
that point onward can discover a missing capability, because every adapter
call the plan will make was checked up front.

The two envelope models the engine constructs and returns —
:class:`ScenarioStepStatus` and :class:`ScenarioRunStatus` — are defined
here rather than in :mod:`server.scenario_routes`, even though
``docs/designs/scenario-generator.md`` §4.4 groups them with that module's
HTTP furniture. :mod:`server.scenario_routes` needs :func:`start_run` /
:func:`get_run_status` / :func:`reset_scenarios` from this module, so a
model importable only from ``scenario_routes`` would make the two modules
import each other. Owning the run-status models next to the code that
mutates run state is the same posture the codebase already uses for
:class:`~core.failures.ArmedFailure` / :class:`~core.failures.FailuresStatus`,
which live beside :class:`~core.failure_scheduler.FailureScheduler` rather
than in ``server/failure_routes.py``. ``scenario_routes.py`` imports these
models back for its ``response_model`` declarations — no wire-format change
from what the design specifies.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from core.models import AircraftSetup
from core.navdata.provider import NavdataProvider
from core.placements import PlacementRequest
from core.scenarios.loader import LoadedScenario
from core.scenarios.models import ScenarioDocument, ScenarioFailuresBlock
from core.scenarios.preflight import missing_capabilities
from core.sim_adapter import CapabilityNotSupported, SimAdapter
from core.weather.models import WeatherRequest, WeatherSetup
from core.weather.presets import resolve_request
from server.failure_routes import arm_failure
from server.position_routes import ApplyPlacementRequest, execute_placement

__all__ = [
    "ScenarioAlreadyRunning",
    "ScenarioCapabilitiesMissing",
    "ScenarioRunStatus",
    "ScenarioStepName",
    "ScenarioStepStatus",
    "ScenarioStepStatusValue",
    "get_run_status",
    "reset_scenarios",
    "start_run",
]

logger = logging.getLogger(__name__)

ScenarioStepName = Literal["weather", "aircraft_state", "position", "failures", "traffic"]
ScenarioStepStatusValue = Literal["pending", "running", "done", "failed"]


class ScenarioStepStatus(BaseModel):
    """One declared step's progress. Only the blocks a scenario declares appear."""

    name: ScenarioStepName
    status: ScenarioStepStatusValue
    detail: str | None = None
    error: str | None = None


class ScenarioRunStatus(BaseModel):
    """The whole run's progress — what ``GET /api/scenarios/run`` polls."""

    scenario_id: str
    status: Literal["running", "completed", "failed"]
    steps: tuple[ScenarioStepStatus, ...]
    started_at: datetime
    finished_at: datetime | None = None


class ScenarioAlreadyRunning(RuntimeError):
    """Raised by :func:`start_run` when a run is already in progress.

    Carries the id of the run already in progress so the caller
    (``server/scenario_routes.py``) can build the 409 detail sentence.
    """

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        super().__init__(f"A scenario is already running ({scenario_id!r}).")


class ScenarioCapabilitiesMissing(RuntimeError):
    """Raised by :func:`start_run` when the adapter lacks a required capability.

    Carries the missing flags so the caller can build the 501 detail
    sentence naming every one of them.
    """

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"Missing capabilities: {', '.join(missing)}")


class _StepFailure(Exception):
    """Internal control-flow signal: a step already recorded its own failure.

    Never escapes :func:`_execute` — it only stops the fixed-order sequence
    once a step has written its own ``"failed"`` status.
    """


@dataclass
class _StepState:
    status: ScenarioStepStatusValue = "pending"
    detail: str | None = None
    error: str | None = None


@dataclass
class _RunState:
    scenario_id: str
    step_names: tuple[ScenarioStepName, ...]
    steps: dict[ScenarioStepName, _StepState]
    status: Literal["running", "completed", "failed"] = "running"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def snapshot(self) -> ScenarioRunStatus:
        return ScenarioRunStatus(
            scenario_id=self.scenario_id,
            status=self.status,
            steps=tuple(
                ScenarioStepStatus(
                    name=name,
                    status=self.steps[name].status,
                    detail=self.steps[name].detail,
                    error=self.steps[name].error,
                )
                for name in self.step_names
            ),
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


#: The scheduler's own module-state posture (``server/failure_routes.py``):
#: exactly one of each per process, not app state.
_current_run: _RunState | None = None
_current_task: asyncio.Task[None] | None = None


def _declared_steps(document: ScenarioDocument) -> tuple[ScenarioStepName, ...]:
    """Which step names this scenario's document will report, in execution order.

    Position and aircraft_state are one call whenever a position is present
    (D7) — both steps appear and flip together in that case, even when the
    document's own ``aircraft_state`` block is empty, because the placement
    itself always carries a setup (speed, at minimum). Only when a scenario
    sets ``aircraft_state`` with no ``position`` does the aircraft_state step
    stand alone.
    """
    steps: list[ScenarioStepName] = []
    if document.weather is not None:
        steps.append("weather")
    if document.position is not None:
        steps.append("aircraft_state")
        steps.append("position")
    elif document.aircraft_state is not None:
        steps.append("aircraft_state")
    if document.failures is not None:
        steps.append("failures")
    if document.traffic is not None:
        steps.append("traffic")
    return tuple(steps)


def _fail_step(state: _RunState, name: ScenarioStepName, error: Exception) -> None:
    message = error.detail if isinstance(error, HTTPException) else str(error)
    state.steps[name].status = "failed"
    state.steps[name].error = str(message)


def _done_step(state: _RunState, name: ScenarioStepName, detail: str | None = None) -> None:
    state.steps[name].status = "done"
    state.steps[name].detail = detail


def _weather_context(
    navdata: NavdataProvider, request: WeatherRequest
) -> tuple[float | None, float | None]:
    """The runway bearing / field elevation a weather request names, or ``(None, None)``.

    Mirrors ``server/weather_routes.py``'s own ``_resolve_context``, but
    raises :class:`ValueError` rather than :class:`~fastapi.HTTPException`
    for an unresolvable airport/runway — a scenario run has no HTTP request
    to answer, and ``ValueError`` is one of the three exception types a step
    is allowed to fail with (§6.3).
    """
    if request.airport_icao is None:
        return None, None

    airport = navdata.get_airport(request.airport_icao)
    if airport is None:
        raise ValueError(
            f"Airport {request.airport_icao.upper()!r} is not in the navigation index."
        )
    field_elevation_ft = airport.elevation_ft

    runway_true_bearing_deg: float | None = None
    if request.runway_ident is not None:
        runway = navdata.get_runway(request.airport_icao, request.runway_ident)
        if runway is None:
            raise ValueError(
                f"Runway {request.runway_ident.upper()} is not published at "
                f"{request.airport_icao.upper()}."
            )
        runway_true_bearing_deg = runway.true_bearing_deg

    return runway_true_bearing_deg, field_elevation_ft


def _resolve_weather(
    navdata: NavdataProvider, request: WeatherRequest
) -> tuple[WeatherSetup, tuple[str, ...]]:
    runway_true_bearing_deg, field_elevation_ft = _weather_context(navdata, request)
    return resolve_request(
        request,
        runway_true_bearing_deg=runway_true_bearing_deg,
        field_elevation_ft=field_elevation_ft,
    )


async def _run_weather_step(
    request: WeatherRequest, *, adapter: SimAdapter, navdata: NavdataProvider, state: _RunState
) -> None:
    state.steps["weather"].status = "running"
    try:
        setup, notes = await run_in_threadpool(_resolve_weather, navdata, request)
        await adapter.set_weather(setup)
    except (CapabilityNotSupported, HTTPException, ValueError) as exc:
        _fail_step(state, "weather", exc)
        raise _StepFailure from exc
    _done_step(state, "weather", "; ".join(notes) if notes else None)


async def _run_position_step(
    placement: PlacementRequest,
    setup: AircraftSetup | None,
    *,
    adapter: SimAdapter,
    navdata: NavdataProvider,
    state: _RunState,
) -> None:
    state.steps["aircraft_state"].status = "running"
    state.steps["position"].status = "running"
    try:
        result = await execute_placement(
            ApplyPlacementRequest(placement=placement, setup=setup),
            adapter=adapter,
            navdata=navdata,
        )
    except (CapabilityNotSupported, HTTPException, ValueError) as exc:
        _fail_step(state, "aircraft_state", exc)
        _fail_step(state, "position", exc)
        raise _StepFailure from exc
    detail = f"Placed at {result.placement.label!r}."
    _done_step(state, "aircraft_state", detail)
    _done_step(state, "position", detail)


async def _run_aircraft_state_only_step(
    setup: AircraftSetup, *, adapter: SimAdapter, state: _RunState
) -> None:
    state.steps["aircraft_state"].status = "running"
    try:
        await adapter.apply_setup(setup)
    except (CapabilityNotSupported, HTTPException, ValueError) as exc:
        _fail_step(state, "aircraft_state", exc)
        raise _StepFailure from exc
    _done_step(state, "aircraft_state")


async def _run_failures_step(
    block: ScenarioFailuresBlock, *, adapter: SimAdapter, state: _RunState
) -> None:
    state.steps["failures"].status = "running"
    try:
        for ref in block.immediate:
            await adapter.inject_failure(ref)
        for request in block.armed:
            await arm_failure(request, adapter=adapter)
    except (CapabilityNotSupported, HTTPException, ValueError) as exc:
        _fail_step(state, "failures", exc)
        raise _StepFailure from exc
    _done_step(state, "failures", f"{len(block.immediate)} injected, {len(block.armed)} armed")


async def _execute(
    document: ScenarioDocument, *, adapter: SimAdapter, navdata: NavdataProvider, state: _RunState
) -> None:
    """Run the fixed order: weather -> aircraft_state+position -> failures -> traffic.

    Stops at the first step that raises one of the three recognised
    exception types (§6.3) — remaining steps stay ``"pending"``. A step
    raising anything else is a defensive fallback (not part of the design's
    own exception list): it is still caught here so the run never gets stuck
    reporting ``"running"`` forever, and is logged as unexpected.
    """
    try:
        weather = document.weather
        if weather is not None:
            await _run_weather_step(weather, adapter=adapter, navdata=navdata, state=state)

        position = document.position
        aircraft_state = document.aircraft_state
        if position is not None:
            await _run_position_step(
                position, aircraft_state, adapter=adapter, navdata=navdata, state=state
            )
        elif aircraft_state is not None:
            await _run_aircraft_state_only_step(aircraft_state, adapter=adapter, state=state)

        failures = document.failures
        if failures is not None:
            await _run_failures_step(failures, adapter=adapter, state=state)

        if document.traffic is not None:
            # No executable body in Phase 2: SimAdapter.spawn_traffic() does
            # not exist yet (#13, Phase 3). Provably unreachable today —
            # the pre-flight check already refused any scenario needing
            # can_spawn_traffic, and no adapter declares it True. A single
            # guarded no-op so #13 adds one call here, not a restructure.
            _done_step(state, "traffic", "No spawn geometry executed yet (Phase 3).")

        state.status = "completed"
    except _StepFailure:
        state.status = "failed"
    except Exception:
        logger.exception("Scenario %r run failed unexpectedly", state.scenario_id)
        state.status = "failed"
    finally:
        state.finished_at = datetime.now(UTC)


async def start_run(
    loaded: LoadedScenario, *, adapter: SimAdapter, navdata: NavdataProvider
) -> ScenarioRunStatus:
    """Pre-flight check, then start the background run.

    Raises :class:`ScenarioCapabilitiesMissing` (before any task is created —
    the adapter is never called) when a required capability is not declared,
    and :class:`ScenarioAlreadyRunning` when a scenario is already in
    progress. Otherwise starts the background task and returns the initial,
    all-``"pending"`` snapshot.
    """
    global _current_run, _current_task

    missing = missing_capabilities(loaded.document, adapter.capabilities)
    if missing:
        raise ScenarioCapabilitiesMissing(missing)

    if _current_run is not None and _current_run.status == "running":
        raise ScenarioAlreadyRunning(_current_run.scenario_id)

    step_names = _declared_steps(loaded.document)
    state = _RunState(
        scenario_id=loaded.id,
        step_names=step_names,
        steps={name: _StepState() for name in step_names},
    )
    _current_run = state
    _current_task = asyncio.create_task(
        _execute(loaded.document, adapter=adapter, navdata=navdata, state=state)
    )
    return state.snapshot()


def get_run_status() -> ScenarioRunStatus | None:
    """The current or most recently finished run's status. ``None`` if nothing has run."""
    if _current_run is None:
        return None
    return _current_run.snapshot()


def reset_scenarios() -> None:
    """Cancel any running task and drop the singleton.

    The ``reset_failures()`` pattern, for tests.
    """
    global _current_run, _current_task
    task = _current_task
    _current_task = None
    _current_run = None
    if task is not None:
        task.cancel()
