"""``/api/failures/*`` — inject, arm and clear failures; CLEAR ALL.

Per ``docs/designs/failures-manager.md`` §2 and §6.3.

**Three modes, one endpoint set.** Immediate injection (``/inject``), armed
failures scheduled on a live-telemetry trigger (``/arm``, ``DELETE
/armed/{id}``), and repair (``/clear``, ``/clear-all``). ``/status`` is the one
read the panel polls: its ``active`` list comes from
``adapter.get_active_failures()`` — the simulator's own truth — never from a
ledger this module keeps, because a teleport's ``sim/operation/fix_all_systems``
repairs every failure behind any ledger's back (D10). Its ``armed`` list comes
from :class:`~core.failure_scheduler.FailureScheduler`, which is the only
honest home for arming state (D5): X-Plane's own armed modes share one global
trigger value across every armed failure, which cannot express two failures
armed at two different altitudes.

**The watcher is the one place a timer honestly runs.** The scheduler itself
is pure and synchronous (no asyncio, no clock, see ``core/failure_scheduler.py``);
this module owns a single background ``asyncio.Task`` that consumes
``adapter.stream_state(FAILURE_EVAL_INTERVAL_S)``, evaluates the scheduler
against each frame and injects whatever fires. It is started lazily on the
first ``/arm`` and stopped once nothing is armed — no armed failures, no
background traffic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.failure_scheduler import FailureScheduler
from core.failures import (
    FAILURE_CATALOGUE,
    ArmedFailure,
    ArmFailureRequest,
    ClearFailureRequest,
    FailureCategory,
    FailureId,
    FailureRef,
    FailuresStatus,
    InjectFailureRequest,
)
from core.sim_adapter import CapabilityNotSupported
from server._shared import _require_capability
from server.constants import CAPABILITY_UNAVAILABLE_STATUS
from server.constants import POLL_INTERVAL_S as FAILURE_EVAL_INTERVAL_S
from server.deps import get_adapter

if TYPE_CHECKING:
    from core.failures import FailureSpec, FailureSupport
    from core.sim_adapter import SimAdapter

__all__ = [
    "FAILURE_EVAL_INTERVAL_S",
    "FailureCatalogueEntry",
    "FailureCatalogueResponse",
    "arm_failure",
    "reset_failures",
    "router",
]

logger = logging.getLogger(__name__)

#: How long the watcher waits before re-entering ``stream_state`` after the
#: stream itself dies (adapter disconnected). Short enough that a reconnected
#: simulator resumes quickly, long enough not to spin a dead one.
_WATCHER_BACKOFF_S = 1.0

router = APIRouter(prefix="/api/failures", tags=["failures"])

#: The scheduler and its watcher task are module state, not app state — there
#: is exactly one of each per process, the same posture as the navdata index
#: build in ``server/navdata_routes.py``.
_scheduler = FailureScheduler()
_watcher_task: asyncio.Task[None] | None = None


class FailureCatalogueEntry(BaseModel):
    """One catalogue entry, resolved against the active adapter's support manifest."""

    failure_id: FailureId
    label: str
    category: FailureCategory
    takes_engine_index: bool
    description: str
    supported: bool
    best_effort: bool
    reason: str | None


class FailureCatalogueResponse(BaseModel):
    """The full catalogue, in display order, merged with the adapter's support manifest."""

    adapter: str
    caveat: str | None
    failures: list[FailureCatalogueEntry]


# ---------------------------------------------------------------------------
# Capability gating (D14, §2.1)
# ---------------------------------------------------------------------------


async def _require_failure_support(adapter: SimAdapter, ref: FailureRef) -> None:
    """Refuse when either the group capability or this one catalogue entry is unsupported.

    Nobody should ever reach this: the panel disables per entry from
    ``/catalogue`` before a request is sent (§7.4, fail-closed while loading).
    Reaching it means a caller ignored the manifest, and the same 501 applies
    either way — a well-formed request the active simulator has no
    implementation behind.
    """
    _require_capability(adapter, "can_inject_failures", "inject or clear failures")
    manifest = await adapter.get_failure_support()
    support = next(
        (entry for entry in manifest.entries if entry.failure_id == ref.failure_id), None
    )
    if support is not None and not support.supported:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=support.reason or f"{ref.failure_id!r} is not supported on this adapter.",
        )


async def _current_status(adapter: SimAdapter) -> FailuresStatus:
    """``active`` read back from the simulator (D10), ``armed`` from the scheduler."""
    active = list(await adapter.get_active_failures())
    return FailuresStatus(active=active, armed=list(_scheduler.armed))


def _catalogue_entry(
    spec: FailureSpec, support: FailureSupport | None, *, adapter_name: str
) -> FailureCatalogueEntry:
    """One catalogue row, resolved against ``support`` — the adapter's manifest entry for it.

    ``support`` is ``None`` only when an adapter's manifest omits an id it
    should always carry (a bug in that adapter); the row still renders,
    disabled, rather than the whole catalogue request failing for it.
    """
    if support is None:
        return FailureCatalogueEntry(
            failure_id=spec.failure_id,
            label=spec.label,
            category=spec.category,
            takes_engine_index=spec.takes_engine_index,
            description=spec.description,
            supported=False,
            best_effort=False,
            reason=f"The {adapter_name!r} adapter's support manifest carries no entry "
            f"for {spec.failure_id!r}.",
        )
    return FailureCatalogueEntry(
        failure_id=spec.failure_id,
        label=spec.label,
        category=spec.category,
        takes_engine_index=spec.takes_engine_index,
        description=spec.description,
        supported=support.supported,
        best_effort=support.best_effort,
        reason=support.reason,
    )


# ---------------------------------------------------------------------------
# The watcher (§6.3)
# ---------------------------------------------------------------------------


def _ensure_watcher_running() -> None:
    """Start the watcher task if it is not already running. Idempotent."""
    global _watcher_task
    if _watcher_task is not None and not _watcher_task.done():
        return
    _watcher_task = asyncio.create_task(_watch())


def _stop_watcher_if_idle() -> None:
    """Cancel the watcher once nothing is armed. No armed failures, no background traffic."""
    global _watcher_task
    if _scheduler.armed:
        return
    task = _watcher_task
    _watcher_task = None
    if task is not None:
        task.cancel()


async def _watch() -> None:
    """Evaluate armed failures against live telemetry until none remain armed.

    For each fired trigger: inject immediately; on failure, put the entry back
    armed with ``last_error`` set (:meth:`~core.failure_scheduler.FailureScheduler.restore`) so
    it is retried on the next satisfying frame — an unreachable simulator
    delays a firing instead of losing it.

    If the telemetry stream itself dies, back off and re-enter while anything
    stays armed. Nothing evaluates while telemetry is down, including delay
    triggers whose deadline may pass while it is: they fire on the first frame
    after telemetry resumes. That is stated, not hidden — injecting into a
    dead simulator is impossible anyway, and "fires late, visibly" beats
    "fires never, silently".
    """
    own_task = asyncio.current_task()
    adapter = get_adapter()
    try:
        while _scheduler.armed:
            try:
                async for state in adapter.stream_state(FAILURE_EVAL_INTERVAL_S):
                    if not _scheduler.armed:
                        return
                    fired = _scheduler.evaluate(state, now_monotonic=time.monotonic())
                    for entry in fired:
                        ref = FailureRef(
                            failure_id=entry.failure_id, engine_index=entry.engine_index
                        )
                        try:
                            await adapter.inject_failure(ref)
                        except Exception as exc:  # any inject failure retries, never drops
                            logger.warning(
                                "Armed failure %s (%s) failed to inject; retrying: %s",
                                entry.armed_id,
                                entry.failure_id,
                                exc,
                            )
                            _scheduler.restore(entry, error=str(exc))
                    if not _scheduler.armed:
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failure watcher's telemetry stream failed; retrying")
                if not _scheduler.armed:
                    return
                await asyncio.sleep(_WATCHER_BACKOFF_S)
    finally:
        global _watcher_task
        if _watcher_task is own_task:
            _watcher_task = None


def reset_failures() -> None:
    """Clear the scheduler and cancel the watcher. The ``reset_adapter()`` pattern, for tests."""
    global _watcher_task
    task = _watcher_task
    _watcher_task = None
    _scheduler.disarm_all()
    if task is not None:
        task.cancel()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/catalogue", response_model=FailureCatalogueResponse)
async def get_catalogue() -> FailureCatalogueResponse:
    """The whole catalogue, merged with the adapter's support manifest.

    Capability-free (§2.1): it answers "what could I do here?" even when the
    answer is "nothing, and here is why" for every entry.
    """
    adapter = get_adapter()
    manifest = await adapter.get_failure_support()
    support_by_id = {entry.failure_id: entry for entry in manifest.entries}
    failures = [
        _catalogue_entry(spec, support_by_id.get(spec.failure_id), adapter_name=adapter.name)
        for spec in FAILURE_CATALOGUE
    ]
    return FailureCatalogueResponse(adapter=adapter.name, caveat=manifest.caveat, failures=failures)


@router.get("/status", response_model=FailuresStatus)
async def get_status() -> FailuresStatus:
    """Active failures (the simulator's truth, D10) plus armed ones (the scheduler)."""
    return await _current_status(get_adapter())


@router.post("/inject", response_model=FailuresStatus)
async def inject_failure(request: InjectFailureRequest) -> FailuresStatus:
    """Fail one system now. Injecting an already-failed system is a no-op."""
    adapter = get_adapter()
    await _require_failure_support(adapter, request)
    try:
        await adapter.inject_failure(request)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return await _current_status(adapter)


async def arm_failure(request: ArmFailureRequest, *, adapter: SimAdapter) -> ArmedFailure:
    """Register one armed failure with a trigger. Not idempotent — arming twice arms two.

    Factored out of ``POST /api/failures/arm`` so the Scenario Generator arms
    into the SAME scheduler/watcher instance rather than running a second one
    (D8, ``docs/designs/scenario-generator.md`` §5.3/§6.2). Starts the watcher
    task lazily, exactly as the route already did.
    """
    await _require_failure_support(adapter, request)
    armed = _scheduler.arm(request, now_monotonic=time.monotonic(), armed_at=datetime.now(UTC))
    _ensure_watcher_running()
    return armed


@router.post("/arm", response_model=ArmedFailure)
async def arm_failure_route(request: ArmFailureRequest) -> ArmedFailure:
    return await arm_failure(request, adapter=get_adapter())


@router.delete("/armed/{armed_id}", response_model=FailuresStatus)
async def disarm_failure(armed_id: str) -> FailuresStatus:
    """Disarm one armed failure before it fires. 404 when it may have already fired."""
    if not _scheduler.disarm(armed_id):
        raise HTTPException(
            status_code=404,
            detail=f"No armed failure {armed_id!r} — it may have already fired.",
        )
    _stop_watcher_if_idle()
    return await _current_status(get_adapter())


@router.post("/clear", response_model=FailuresStatus)
async def clear_failure(request: ClearFailureRequest) -> FailuresStatus:
    """Repair one active failure. Clearing something that is not failed is a no-op."""
    adapter = get_adapter()
    await _require_failure_support(adapter, request)
    try:
        await adapter.clear_failure(request)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return await _current_status(adapter)


@router.post("/clear-all", response_model=FailuresStatus)
async def clear_all_failures() -> FailuresStatus:
    """Repair every active failure and disarm every armed one (D12) — the one-tap reset."""
    adapter = get_adapter()
    _require_capability(adapter, "can_inject_failures", "clear failures")
    try:
        await adapter.clear_all_failures()
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    _scheduler.disarm_all()
    _stop_watcher_if_idle()
    return await _current_status(adapter)
