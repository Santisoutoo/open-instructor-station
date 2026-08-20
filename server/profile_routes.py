"""``/api/profiles/*`` — save, list, apply, import and export training profiles.

Per ``docs/designs/training-profiles.md`` §2, as revised by this manager's own
as-built addendum (see that document): a training profile embeds
``core.scenarios.models.ScenarioDocument`` directly, so applying one composes
the Position, Weather and Failures managers' own apply paths exactly as a
scenario run does — **except independently per component (D8)**, which is
the one place this module's orchestration diverges from
``server/scenario_engine.py``'s fixed-order, stop-at-first-failure run: a
profile's position, weather and every failure entry are each attempted on
their own, and one component's failure never prevents another's attempt.
``POST .../apply`` is therefore (almost) always 200 — partial application is
reported in the body (``degraded`` plus a per-component outcome and reason),
never as a 4xx/5xx. Only "the profile itself does not exist" is a 404.

None of the CRUD endpoints or import/export touch the simulator or navdata
(D3 — no new ``Capabilities`` flag, no ``SimAdapter`` method), so none of
them is ever 501 or 503; only ``apply`` reaches the adapter, and it reports
refusal inside its 200 body instead.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError

from core.failures import FailureRef
from core.navdata.provider import NavdataProvider, NavdataUnavailable
from core.profiles.models import ProfileSummary, TrainingProfile, TrainingProfileCreate
from core.profiles.store import ProfileStore, ProfileStoreError
from core.scenarios.models import ScenarioDocument
from core.sim_adapter import CapabilityNotSupported, SimAdapter, WeatherRejected
from server.deps import get_adapter, get_navdata, get_profile_store
from server.failure_routes import arm_failure
from server.position_routes import ApplyPlacementRequest, PlacementResult, execute_placement
from server.weather_routes import WeatherApplyResult
from server.weather_routes import _resolve as _resolve_weather

__all__ = [
    "IMPORT_VALIDATION_STATUS",
    "ProfileApplyResult",
    "ProfileFailureOutcome",
    "ProfilePositionOutcome",
    "ProfileWeatherOutcome",
    "apply_profile",
    "router",
]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

_NOT_FOUND = "No training profile {id!r}."
_MAY_BE_DELETED = "No training profile {id!r} — it may already be deleted."

#: An uploaded ``.json`` that does not validate as a
#: :class:`~core.profiles.models.TrainingProfile`. The upload is well-formed
#: as a request, the *content* fails the schema — no partial import.
IMPORT_VALIDATION_STATUS = 422


# ---------------------------------------------------------------------------
# The apply outcome — HTTP furniture (§3.4). Embeds other managers' own
# response models directly, since this file is server-side composing
# server-side.
# ---------------------------------------------------------------------------


class ProfilePositionOutcome(BaseModel):
    """The position + aircraft-state step's outcome.

    **Deviation from the original design draft, and a consequence of
    embedding ``ScenarioDocument`` (see the design's as-built addendum):**
    ``attempted`` did not exist in the design's own sketch of this model,
    because its ``ProfileScenario.placement`` was a required field — always
    present. ``ScenarioDocument.position`` is optional (a profile may carry
    only weather, or only failures), so this mirrors
    :class:`ProfileWeatherOutcome`'s own ``attempted`` flag rather than
    assuming position is always attempted.
    """

    attempted: bool
    applied: bool
    result: PlacementResult | None = None
    reason: str | None = None


class ProfileWeatherOutcome(BaseModel):
    attempted: bool
    applied: bool
    result: WeatherApplyResult | None = None
    reason: str | None = None


class ProfileFailureOutcome(BaseModel):
    ref: FailureRef
    applied: bool
    armed: bool = False  #: True = registered with a trigger, not injected.
    armed_id: str | None = None  #: Set iff armed is True and applied is True.
    reason: str | None = None


class ProfileApplyResult(BaseModel):
    profile_id: str
    position: ProfilePositionOutcome
    weather: ProfileWeatherOutcome
    failures: tuple[ProfileFailureOutcome, ...]
    degraded: bool
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _require_profile(store: ProfileStore, profile_id: str) -> TrainingProfile:
    profile = store.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND.format(id=profile_id))
    return profile


def _reason(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


def _unexpected_reason(exc: Exception, *, component: str, profile_id: str) -> str:
    """Log and stringify an exception none of the expected types anticipated.

    D8's whole contract is that one component's failure never prevents another's
    attempt — an adapter-specific exception this module cannot enumerate up front
    (``XPlaneRepositionFailed``, ``XPlaneNotReachable``, a connection drop mid-call)
    must not be allowed to propagate out of ``apply_profile`` and abort the
    components after it, the way an unguarded ``server/scenario_engine.py`` step
    already once needed a defensive fallback for (see its own module docstring).
    """
    logger.exception("Profile %r: %s failed unexpectedly", profile_id, component)
    return _reason(exc)


# ---------------------------------------------------------------------------
# Apply orchestration (D10: lives here, not in core/ — resolving what
# degrades means calling the adapter through the other managers' own apply
# paths, and core/ never talks to a simulator).
# ---------------------------------------------------------------------------


async def _apply_position(
    document: ScenarioDocument, *, adapter: SimAdapter, navdata: NavdataProvider, profile_id: str
) -> ProfilePositionOutcome:
    placement = document.position
    setup = document.aircraft_state
    if placement is None and setup is None:
        return ProfilePositionOutcome(attempted=False, applied=True)
    try:
        if placement is not None:
            result = await execute_placement(
                ApplyPlacementRequest(placement=placement, setup=setup),
                adapter=adapter,
                navdata=navdata,
            )
            return ProfilePositionOutcome(attempted=True, applied=True, result=result)
        assert setup is not None  # narrowed by the guard above
        await adapter.apply_setup(setup)
        return ProfilePositionOutcome(attempted=True, applied=True)
    except (HTTPException, CapabilityNotSupported, NavdataUnavailable, ValueError) as exc:
        return ProfilePositionOutcome(attempted=True, applied=False, reason=_reason(exc))
    except Exception as exc:  # D8's own defensive fallback, see _unexpected_reason
        reason = _unexpected_reason(exc, component="position", profile_id=profile_id)
        return ProfilePositionOutcome(attempted=True, applied=False, reason=reason)


async def _apply_weather(
    document: ScenarioDocument, *, adapter: SimAdapter, navdata: NavdataProvider, profile_id: str
) -> ProfileWeatherOutcome:
    request = document.weather
    if request is None:
        return ProfileWeatherOutcome(attempted=False, applied=True)
    try:
        setup, notes = await run_in_threadpool(_resolve_weather, navdata, request)
        await adapter.set_weather(setup)
        state = await adapter.get_weather()
    except (
        HTTPException,
        CapabilityNotSupported,
        WeatherRejected,
        NavdataUnavailable,
        ValueError,
    ) as exc:
        return ProfileWeatherOutcome(attempted=True, applied=False, reason=_reason(exc))
    except Exception as exc:  # D8's own defensive fallback, see _unexpected_reason
        reason = _unexpected_reason(exc, component="weather", profile_id=profile_id)
        return ProfileWeatherOutcome(attempted=True, applied=False, reason=reason)
    return ProfileWeatherOutcome(
        attempted=True,
        applied=True,
        result=WeatherApplyResult(applied=setup, state=state, notes=notes),
    )


async def _apply_failures(
    document: ScenarioDocument, *, adapter: SimAdapter, profile_id: str
) -> tuple[ProfileFailureOutcome, ...]:
    block = document.failures
    if block is None:
        return ()

    outcomes: list[ProfileFailureOutcome] = []

    for ref in block.immediate:
        try:
            await adapter.inject_failure(ref)
        except (CapabilityNotSupported, HTTPException, ValueError) as exc:
            outcomes.append(
                ProfileFailureOutcome(ref=ref, applied=False, armed=False, reason=_reason(exc))
            )
            continue
        except Exception as exc:  # D8's own defensive fallback
            reason = _unexpected_reason(exc, component="failures", profile_id=profile_id)
            outcomes.append(
                ProfileFailureOutcome(ref=ref, applied=False, armed=False, reason=reason)
            )
            continue
        outcomes.append(ProfileFailureOutcome(ref=ref, applied=True, armed=False))

    for armed_request in block.armed:
        armed_ref = FailureRef(
            failure_id=armed_request.failure_id, engine_index=armed_request.engine_index
        )
        try:
            armed = await arm_failure(armed_request, adapter=adapter)
        except (CapabilityNotSupported, HTTPException, ValueError) as exc:
            outcomes.append(
                ProfileFailureOutcome(
                    ref=armed_ref, applied=False, armed=False, reason=_reason(exc)
                )
            )
            continue
        except Exception as exc:  # D8's own defensive fallback
            reason = _unexpected_reason(exc, component="failures", profile_id=profile_id)
            outcomes.append(
                ProfileFailureOutcome(ref=armed_ref, applied=False, armed=False, reason=reason)
            )
            continue
        outcomes.append(
            ProfileFailureOutcome(ref=armed_ref, applied=True, armed=True, armed_id=armed.armed_id)
        )

    return tuple(outcomes)


def _degraded(
    position: ProfilePositionOutcome,
    weather: ProfileWeatherOutcome,
    failures: tuple[ProfileFailureOutcome, ...],
) -> bool:
    """True iff any *attempted* component did not fully apply.

    A profile with no weather block is never "degraded" for lacking one —
    only components the profile actually asked for count.
    """
    if position.attempted and not position.applied:
        return True
    if weather.attempted and not weather.applied:
        return True
    return any(not outcome.applied for outcome in failures)


def _notes(
    position: ProfilePositionOutcome,
    weather: ProfileWeatherOutcome,
    failures: tuple[ProfileFailureOutcome, ...],
) -> tuple[str, ...]:
    """Human sentences in position -> weather -> failures order, rendered verbatim by the panel."""
    notes: list[str] = []
    if position.attempted:
        if position.applied and position.result is not None:
            notes.append(f"Position: placed at {position.result.placement.label!r}.")
        elif position.applied:
            notes.append("Position: applied.")
        else:
            notes.append(f"Position: not applied — {position.reason}")
    if weather.attempted:
        notes.append(
            "Weather: applied." if weather.applied else f"Weather: not applied — {weather.reason}"
        )
    for outcome in failures:
        if outcome.applied and outcome.armed:
            notes.append(f"{outcome.ref.failure_id}: armed.")
        elif outcome.applied:
            notes.append(f"{outcome.ref.failure_id}: injected.")
        else:
            notes.append(f"{outcome.ref.failure_id}: not applied — {outcome.reason}")
    return tuple(notes)


async def apply_profile(
    profile: TrainingProfile, *, adapter: SimAdapter, navdata: NavdataProvider
) -> ProfileApplyResult:
    """Run a profile's embedded scenario, each component attempted independently (D8)."""
    position = await _apply_position(
        profile.scenario, adapter=adapter, navdata=navdata, profile_id=profile.profile_id
    )
    weather = await _apply_weather(
        profile.scenario, adapter=adapter, navdata=navdata, profile_id=profile.profile_id
    )
    failures = await _apply_failures(
        profile.scenario, adapter=adapter, profile_id=profile.profile_id
    )
    return ProfileApplyResult(
        profile_id=profile.profile_id,
        position=position,
        weather=weather,
        failures=failures,
        degraded=_degraded(position, weather, failures),
        notes=_notes(position, weather, failures),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ProfileSummary])
def list_profiles() -> list[ProfileSummary]:
    """Every saved profile, summarised, newest ``updated_at`` first."""
    return get_profile_store().list()


@router.post("", response_model=TrainingProfile)
def create_profile(draft: TrainingProfileCreate) -> TrainingProfile:
    """Save a new profile. The server assigns ``profile_id`` and timestamps."""
    try:
        return get_profile_store().create(draft)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{profile_id}", response_model=TrainingProfile)
def get_profile(profile_id: str) -> TrainingProfile:
    """One profile, in full."""
    return _require_profile(get_profile_store(), profile_id)


@router.put("/{profile_id}", response_model=TrainingProfile)
def replace_profile(profile_id: str, draft: TrainingProfileCreate) -> TrainingProfile:
    """Replace name/description/author/scenario of an existing profile. Never creates (D13)."""
    try:
        profile = get_profile_store().replace(profile_id, draft)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND.format(id=profile_id))
    return profile


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str) -> Response:
    """Remove a profile. 404 with 'may already be deleted' when it is already gone."""
    try:
        deleted = get_profile_store().delete(profile_id)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=_MAY_BE_DELETED.format(id=profile_id))
    return Response(status_code=204)


@router.post("/{profile_id}/apply", response_model=ProfileApplyResult)
async def apply_profile_route(profile_id: str) -> ProfileApplyResult:
    """Run the embedded scenario, each component attempted independently (D8).

    Almost always 200 — only an unknown ``profile_id`` is a 404. Partial
    application is reported in the body, never as a 4xx/5xx.
    """
    store = get_profile_store()
    profile = _require_profile(store, profile_id)
    return await apply_profile(profile, adapter=get_adapter(), navdata=get_navdata())


@router.post("/import", response_model=TrainingProfile)
async def import_profile(file: UploadFile = File(...)) -> TrainingProfile:
    """Upload a ``.json`` file exported from this or another instance.

    Always assigns a fresh ``profile_id`` (D7): any embedded id or timestamps
    in the upload are ignored. 422 on malformed or non-validating content, no
    partial import.
    """
    raw = await file.read()
    try:
        return get_profile_store().import_bytes(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=IMPORT_VALIDATION_STATUS, detail=str(exc)) from exc
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{profile_id}/export")
def export_profile(profile_id: str) -> Response:
    """Download the profile as a ``.json`` file (``Content-Disposition: attachment``)."""
    raw = get_profile_store().export_bytes(profile_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=_MAY_BE_DELETED.format(id=profile_id))
    return Response(
        content=raw,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{profile_id}.json"'},
    )
