"""``/api/scenarios/*`` — the shipped scenario catalogue, and running one.

Per ``docs/designs/scenario-generator.md`` §3. Four endpoints, REST plus poll
(D9), no WebSocket:

* ``GET  /api/scenarios``          -> :class:`ScenarioManifest`
* ``GET  /api/scenarios/run``      -> :class:`~server.scenario_engine.ScenarioRunStatus` | ``null``
* ``GET  /api/scenarios/{id}``     -> :class:`ScenarioDetail`
* ``POST /api/scenarios/{id}/run`` -> :class:`~server.scenario_engine.ScenarioRunStatus`

**``GET /run`` is registered before ``GET /{scenario_id}``.** Both are
two-segment ``GET`` paths under this router's prefix, and FastAPI/Starlette
matches routes in registration order — ``{scenario_id}`` would otherwise
swallow ``run`` as a (nonexistent) scenario id.

**The manifest re-parses the shipped directory on every call (D12).**
Fourteen small files, no cache: unlike navdata's SQLite cache, which exists
because CIFP parsing is genuinely expensive, this is not.

**Availability is computed per scenario (D11).** There is no single gating
capability for the whole manager the way Weather/Failures have one — the
manifest always renders, and each row states its own ``available``/``reason``
against ``core.scenarios.preflight.missing_capabilities``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.scenarios.loader import LoadedScenario, load_all_scenarios
from core.scenarios.models import ScenarioDocument
from core.scenarios.preflight import missing_capabilities
from core.sim_adapter import Capabilities
from server._shared import _not_found_or_404
from server.constants import CAPABILITY_UNAVAILABLE_STATUS
from server.deps import get_adapter, get_navdata
from server.scenario_engine import (
    ScenarioAlreadyRunning,
    ScenarioCapabilitiesMissing,
    ScenarioRunStatus,
    get_run_status,
    start_run,
)

__all__ = [
    "ScenarioDetail",
    "ScenarioManifest",
    "ScenarioSummary",
    "router",
]

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


# ---------------------------------------------------------------------------
# Response envelopes — HTTP furniture (manifest/listing concerns; the run
# status models live in server.scenario_engine, which owns and mutates run
# state — see that module's docstring for why).
# ---------------------------------------------------------------------------


class ScenarioSummary(BaseModel):
    """One manifest row."""

    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    available: bool
    reason: str | None = None


class ScenarioDetail(ScenarioSummary):
    """One scenario's full document plus its availability, for a preview view."""

    document: ScenarioDocument


class ScenarioManifest(BaseModel):
    """Every shipped scenario, whether it can run on the active adapter, and why not."""

    adapter: str
    scenarios: tuple[ScenarioSummary, ...]
    load_errors: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unavailable_reason(adapter_name: str, scenario_id: str, missing: tuple[str, ...]) -> str:
    """The one sentence naming every missing capability flag, comma-joined."""
    return (
        f"Unavailable on this adapter — the {adapter_name!r} adapter does not declare "
        f"{', '.join(missing)}, so {scenario_id!r} cannot run."
    )


def _summary(
    loaded: LoadedScenario, capabilities: Capabilities, *, adapter_name: str
) -> ScenarioSummary:
    """One scenario's manifest row, resolved against ``capabilities``."""
    missing = missing_capabilities(loaded.document, capabilities)
    reason = _unavailable_reason(adapter_name, loaded.id, missing) if missing else None
    return ScenarioSummary(
        id=loaded.id,
        name=loaded.document.name,
        description=loaded.document.description,
        tags=loaded.document.tags,
        available=not missing,
        reason=reason,
    )


def _find_or_404(scenario_id: str) -> LoadedScenario:
    """Load and return the scenario named ``scenario_id``, or raise a 404."""
    loaded, _errors = load_all_scenarios()
    found = next((item for item in loaded if item.id == scenario_id), None)
    return _not_found_or_404(found, f"Scenario {scenario_id!r} is not defined.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ``def``, not ``async def`` — loading the shipped YAML files is filesystem
# and pydantic work, never an adapter call, the same reasoning as
# ``position_routes.preview_placement`` / ``weather_routes.preview_weather``.
@router.get("", response_model=ScenarioManifest)
def get_scenarios() -> ScenarioManifest:
    """Every shipped scenario, with ``available``/``reason`` against the active adapter."""
    adapter = get_adapter()
    loaded, errors = load_all_scenarios()
    scenarios = tuple(
        sorted(
            (_summary(item, adapter.capabilities, adapter_name=adapter.name) for item in loaded),
            key=lambda summary: summary.id,
        )
    )
    return ScenarioManifest(
        adapter=adapter.name,
        scenarios=scenarios,
        load_errors=tuple(str(error) for error in errors),
    )


@router.get("/run", response_model=ScenarioRunStatus | None)
def get_current_run() -> ScenarioRunStatus | None:
    """The current or most recently finished run's status. ``null`` if nothing has run."""
    return get_run_status()


@router.get("/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(scenario_id: str) -> ScenarioDetail:
    """One scenario's full document plus its availability."""
    adapter = get_adapter()
    loaded = _find_or_404(scenario_id)
    summary = _summary(loaded, adapter.capabilities, adapter_name=adapter.name)
    return ScenarioDetail(**summary.model_dump(), document=loaded.document)


@router.post("/{scenario_id}/run", response_model=ScenarioRunStatus)
async def run_scenario(scenario_id: str) -> ScenarioRunStatus:
    """Pre-flight check, then start the background run (§3.2).

    The adapter is never called when the pre-flight check fails: that is the
    whole mechanism behind "never attempted halfway through".
    """
    adapter = get_adapter()
    navdata = get_navdata()
    loaded = _find_or_404(scenario_id)
    try:
        return await start_run(loaded, adapter=adapter, navdata=navdata)
    except ScenarioCapabilitiesMissing as exc:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=_unavailable_reason(adapter.name, scenario_id, exc.missing),
        ) from exc
    except ScenarioAlreadyRunning as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A scenario is already running ({exc.scenario_id!r}); wait for it to "
                f"finish before starting another."
            ),
        ) from exc
