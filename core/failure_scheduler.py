"""The arming state machine — pure, synchronous, no simulator, no clock of its own.

Per ``docs/designs/failures-manager.md`` §6.2 (D5, D7): armed failures live in
the server, never in the simulator, because X-Plane's own armed modes use
*global* companion datarefs — one shared trigger value for every armed
failure — so two failures armed at different altitudes are inexpressible
there. :class:`FailureScheduler` is the honest home instead: it is fed
telemetry and wall-clock time as plain arguments, never reads either for
itself, which is what makes it testable against a fake clock with zero
mocking of real time.

Trigger semantics — pinned here once so the server and the tests cannot
disagree (§6.2's table):

=============== ================================================ ==============
Trigger         Fires when                                        Units
=============== ================================================ ==============
altitude_above  ``state.altitude_ft >= trigger.altitude_ft``      feet MSL
altitude_below  ``state.altitude_ft <= trigger.altitude_ft``      feet MSL
speed_above     ``state.ias_kt >= trigger.ias_kt``                knots indicated
speed_below     ``state.ias_kt <= trigger.ias_kt``                knots indicated
delay           ``now_monotonic - armed_monotonic >= delay_s``    seconds, wall clock
=============== ================================================ ==============

Level-triggered and inclusive (D7): an armed failure fires on the first
evaluated frame that satisfies its condition, including the frame it was
armed on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from core.failures import (
    AltitudeAboveTrigger,
    AltitudeBelowTrigger,
    ArmedFailure,
    ArmFailureRequest,
    DelayTrigger,
    SpeedAboveTrigger,
    SpeedBelowTrigger,
)

if TYPE_CHECKING:
    from datetime import datetime

    from core.failures import FailureTrigger
    from core.models import AircraftState

__all__ = ["FailureScheduler"]


def _is_satisfied(
    trigger: FailureTrigger,
    state: AircraftState,
    *,
    now_monotonic: float,
    armed_monotonic: float,
) -> bool:
    """Whether ``trigger`` fires against this one frame. The table above, in code."""
    if isinstance(trigger, AltitudeAboveTrigger):
        return state.altitude_ft >= trigger.altitude_ft
    if isinstance(trigger, AltitudeBelowTrigger):
        return state.altitude_ft <= trigger.altitude_ft
    if isinstance(trigger, SpeedAboveTrigger):
        return state.ias_kt >= trigger.ias_kt
    if isinstance(trigger, SpeedBelowTrigger):
        return state.ias_kt <= trigger.ias_kt
    if isinstance(trigger, DelayTrigger):
        return now_monotonic - armed_monotonic >= trigger.delay_s
    # The trigger union is closed (Field(discriminator="type")); an
    # unreachable arm here means the union grew and this function did not.
    raise AssertionError(f"Unhandled trigger type: {trigger!r}")


class FailureScheduler:
    """One instructor's set of armed failures, evaluated frame by frame.

    No asyncio, no adapter, no clock of its own — see the module docstring.
    The server owns the real timer (``server/failure_routes.py``'s watcher);
    this class only ever answers "given this frame, what fires?".
    """

    def __init__(self) -> None:
        self._armed: dict[str, ArmedFailure] = {}
        # Kept independently of ``_armed`` and never dropped on a fire, only
        # on disarm: ``restore`` re-inserts a fired-but-failed entry into
        # ``_armed`` under the same armed_id, and a delay trigger must keep
        # counting from when it was originally armed, not from the retry —
        # otherwise a failed injection would silently reset its own deadline.
        self._armed_monotonic: dict[str, float] = {}

    def arm(
        self, request: ArmFailureRequest, *, now_monotonic: float, armed_at: datetime
    ) -> ArmedFailure:
        """Register one armed failure and return it with its server-assigned id.

        Not idempotent (§2): arming the same failure twice arms two entries.
        """
        armed_id = uuid4().hex
        entry = ArmedFailure(
            failure_id=request.failure_id,
            engine_index=request.engine_index,
            armed_id=armed_id,
            trigger=request.trigger,
            armed_at=armed_at,
        )
        self._armed[armed_id] = entry
        self._armed_monotonic[armed_id] = now_monotonic
        return entry

    def disarm(self, armed_id: str) -> bool:
        """Remove one armed failure before it fires. ``False`` when ``armed_id`` is unknown.

        Only forgets ``armed_id``'s arming time when it was actually still
        armed: an id that has already fired is not in ``_armed`` any more (it
        may be mid-injection, on its way to a possible :meth:`restore`), and
        popping its bookkeeping here would leave a restored entry with no
        arming time to evaluate a delay trigger against.
        """
        existed = self._armed.pop(armed_id, None) is not None
        if existed:
            self._armed_monotonic.pop(armed_id, None)
        return existed

    def disarm_all(self) -> None:
        """Remove every armed failure. Used by CLEAR ALL (D12) and by tests.

        ``_armed_monotonic`` is deliberately left alone: an injection already
        in flight for a just-fired entry may still call :meth:`restore`
        afterwards, and that needs the original arming time (see its
        docstring). The leftover bookkeeping is one float per ever-armed id
        for the scheduler's lifetime — bounded by how many failures one
        session arms, and never read once its entry is gone for good.
        """
        self._armed.clear()

    @property
    def armed(self) -> tuple[ArmedFailure, ...]:
        """Every armed failure, stably ordered by ``armed_at`` then ``armed_id``."""
        return tuple(
            sorted(self._armed.values(), key=lambda entry: (entry.armed_at, entry.armed_id))
        )

    def evaluate(self, state: AircraftState, *, now_monotonic: float) -> tuple[ArmedFailure, ...]:
        """Return every armed failure whose trigger is satisfied by this frame.

        Fired entries are removed from the armed set — the caller (the
        server's watcher) is responsible for injecting them and calling
        :meth:`restore` on any that fail.
        """
        fired: list[ArmedFailure] = []
        for armed_id, entry in list(self._armed.items()):
            armed_monotonic = self._armed_monotonic[armed_id]
            if _is_satisfied(
                entry.trigger,
                state,
                now_monotonic=now_monotonic,
                armed_monotonic=armed_monotonic,
            ):
                fired.append(entry)
                del self._armed[armed_id]
        fired.sort(key=lambda entry: (entry.armed_at, entry.armed_id))
        return tuple(fired)

    def restore(self, entry: ArmedFailure, *, error: str) -> None:
        """Put a fired entry back, with ``last_error`` set, after a failed injection.

        It stays armed and is retried on the next satisfying frame — its
        original ``armed_monotonic`` is preserved (never reset by a retry),
        so a delay trigger does not silently push its own deadline back.
        """
        self._armed[entry.armed_id] = entry.model_copy(update={"last_error": error})
