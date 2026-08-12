"""The live-session restore in ``tests/conftest.py``, proven in CI.

On 2026-08-10 two consecutive ``pytest -m sim`` runs reported 27 passed and
left the user's aircraft wrecked: roll 179.80° (inverted) on one run, 91.62°
(on a wingtip) on the other, ``has_crashed`` true and the flight model still
frozen. The mechanism was pure ordering — the restore put the aircraft back at
ground level while it still believed it was descending at -3443 fpm, and
cleared the crash state *before* that impact registered.

CI has no simulator, so these tests prove the *sequence* instead: they drive
``tests.conftest._restore_and_verify`` with a scripted double that records
every call in order, and pin the four ordering properties that keep a real
aircraft intact, plus the post-condition verification that turns any future
regression into a red run instead of a silently wrecked session. What they do
**not** exercise — X-Plane's actual physics between the writes — is the
``sim-validator``'s job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

import tests.conftest as session_restore
from core.models import AircraftState, GeoPosition
from tests.conftest import LiveAircraftHome, _restore_and_verify

# --------------------------------------------------------------------------
# Scripted double
# --------------------------------------------------------------------------

#: Event names as the double records them, in call order.
FREEZE_ENGAGE = ("freeze", "engage")
FREEZE_RELEASE = ("freeze", "release")

Event = tuple[object, ...]


class ScriptedRestoreSim:
    """Records, in order, every call the session restore makes.

    Mimics the one behavioural detail of ``XPlaneSimAdapter`` the ordering
    depends on: ``frozen_flight_model`` is re-entrant (issue #48), so only the
    outermost block records the engage and the release — exactly like only the
    outermost block writes ``override_planepath`` on the real adapter.
    """

    def __init__(
        self,
        *,
        crashed_at_the_end: bool = False,
        override_at_the_end: int = 0,
        final_state: AircraftState,
        reposition_error: Exception | None = None,
    ) -> None:
        self.events: list[Event] = []
        self._freeze_depth = 0
        self._crashed_at_the_end = crashed_at_the_end
        self._override_at_the_end = override_at_the_end
        self._final_state = final_state
        self._reposition_error = reposition_error

    @asynccontextmanager
    async def frozen_flight_model(self) -> AsyncIterator[None]:
        if self._freeze_depth == 0:
            self.events.append(FREEZE_ENGAGE)
        self._freeze_depth += 1
        try:
            yield
        finally:
            self._freeze_depth -= 1
            if self._freeze_depth == 0:
                self.events.append(FREEZE_RELEASE)

    async def set_position(self, position: GeoPosition, heading_deg: float) -> None:
        self.events.append(("set_position", position, heading_deg))
        if self._reposition_error is not None:
            raise self._reposition_error

    async def clear_crash_state(self) -> None:
        self.events.append(("clear_crash_state",))

    async def has_crashed(self) -> bool:
        self.events.append(("has_crashed",))
        return self._crashed_at_the_end

    async def get_aircraft_state(self) -> AircraftState:
        self.events.append(("get_aircraft_state",))
        return self._final_state

    async def _write(self, key: str, value: float | int | bool, index: int | None = None) -> None:
        self.events.append(("write", key, value, index))

    async def _read(self, key: str) -> object:
        self.events.append(("read", key))
        if key == "override_planepath":
            return [self._override_at_the_end, 0]
        raise AssertionError(f"the restore has no business reading {key!r}")

    async def _true_airspeed_kt(self, ias_kt: float, altitude_ft: float | None = None) -> float:
        self.events.append(("true_airspeed", ias_kt, altitude_ft))
        # A recognisable, monotone conversion: enough to prove the value the
        # velocity vector receives came through the IAS→TAS step.
        return ias_kt * 1.1

    async def _write_velocity_vector(self, heading_deg: float, tas_kt: float) -> None:
        self.events.append(("velocity_vector", heading_deg, tas_kt))

    # -- Assertion helpers -------------------------------------------------

    def index_of(self, event: Event) -> int:
        assert event in self.events, f"{event!r} never happened; events were {self.events!r}"
        return self.events.index(event)

    def first(self, name: str) -> int:
        for i, event in enumerate(self.events):
            if event[0] == name:
                return i
        raise AssertionError(f"no {name!r} event; events were {self.events!r}")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


GROUND_HOME = LiveAircraftHome(
    position=GeoPosition(latitude=40.4700, longitude=-3.5700, altitude_ft=1998.0),
    heading_deg=320.0,
    pitch_deg=-0.6,
    roll_deg=0.2,
    ias_kt=0.0,
    on_ground=True,
)

AIRBORNE_HOME = LiveAircraftHome(
    position=GeoPosition(latitude=40.6000, longitude=-3.4000, altitude_ft=5000.0),
    heading_deg=95.0,
    pitch_deg=2.5,
    roll_deg=-1.0,
    ias_kt=96.0,
    on_ground=False,
)


def restored_state(
    home: LiveAircraftHome, *, pitch: float | None = None, roll: float | None = None
) -> AircraftState:
    """The state a well-behaved restore leaves behind (attitude overridable)."""
    return AircraftState(
        latitude=home.position.latitude,
        longitude=home.position.longitude,
        altitude_ft=home.position.altitude_ft or 0.0,
        heading_deg=home.heading_deg,
        ias_kt=home.ias_kt,
        vertical_speed_fpm=0.0,
        pitch_deg=home.pitch_deg if pitch is None else pitch,
        roll_deg=home.roll_deg if roll is None else roll,
        on_ground=home.on_ground,
    )


@pytest.fixture(autouse=True)
def _no_settle_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 1.5 s release settle is real time for a real simulator, not for CI."""
    monkeypatch.setattr(session_restore, "_RELEASE_SETTLE_S", 0.0)


# --------------------------------------------------------------------------
# The ordering that keeps the aircraft intact
# --------------------------------------------------------------------------


async def test_motion_is_zeroed_inside_the_freeze_before_the_aircraft_moves() -> None:
    """The aircraft must never arrive at ground level still believing it is descending.

    This is the exact defect measured live: restored to the ground carrying
    -3443 fpm, which registered as an impact.
    """
    sim = ScriptedRestoreSim(final_state=restored_state(GROUND_HOME))
    await _restore_and_verify(sim, GROUND_HOME)

    reposition = sim.first("set_position")
    engage = sim.index_of(FREEZE_ENGAGE)
    for key in ("local_vx", "local_vy", "local_vz", "vh_ind_fpm"):
        zeroing = sim.index_of(("write", key, 0.0, None))
        assert engage < zeroing < reposition, (
            f"{key} must be zeroed inside the freeze and before set_position; "
            f"events were {sim.events!r}"
        )


async def test_position_attitude_and_wakeup_velocity_share_one_freeze() -> None:
    """One engage, one release, and every flight-model write between them (issue #37)."""
    sim = ScriptedRestoreSim(final_state=restored_state(GROUND_HOME))
    await _restore_and_verify(sim, GROUND_HOME)

    assert sim.events.count(FREEZE_ENGAGE) == 1
    assert sim.events.count(FREEZE_RELEASE) == 1
    engage = sim.index_of(FREEZE_ENGAGE)
    release = sim.index_of(FREEZE_RELEASE)
    for event_index in (
        sim.first("set_position"),
        sim.index_of(("write", "psi", GROUND_HOME.heading_deg, None)),
        sim.index_of(("write", "theta", GROUND_HOME.pitch_deg, None)),
        sim.index_of(("write", "phi", GROUND_HOME.roll_deg, None)),
        sim.first("velocity_vector"),
    ):
        assert engage < event_index < release, f"events were {sim.events!r}"


async def test_crash_state_is_cleared_after_the_freeze_release_and_nothing_after_it() -> None:
    """``fix_all_systems`` must run after everything that could register as an impact.

    Fired before the release, it clears the *previous* crash and leaves the one
    the release provokes standing — the wreck measured on 2026-08-10. After it,
    only the redundant override release and the read-only verification may run.
    """
    sim = ScriptedRestoreSim(final_state=restored_state(GROUND_HOME))
    await _restore_and_verify(sim, GROUND_HOME)

    clear = sim.first("clear_crash_state")
    assert sim.index_of(FREEZE_RELEASE) < clear

    allowed_afterwards = {"write", "read", "has_crashed", "get_aircraft_state"}
    for event in sim.events[clear + 1 :]:
        assert event[0] in allowed_afterwards, f"{event!r} ran after clear_crash_state"
        if event[0] == "write":
            assert event == ("write", "override_planepath", 0, 0), (
                f"the only write allowed after clear_crash_state is the override "
                f"release, got {event!r}"
            )


async def test_override_is_released_once_more_after_everything_else() -> None:
    """Belt and braces: the last write of the restore is ``override_planepath = 0``."""
    sim = ScriptedRestoreSim(final_state=restored_state(GROUND_HOME))
    await _restore_and_verify(sim, GROUND_HOME)

    writes = [event for event in sim.events if event[0] == "write"]
    assert writes[-1] == ("write", "override_planepath", 0, 0)
    assert sim.first("clear_crash_state") < sim.index_of(("write", "override_planepath", 0, 0))


async def test_override_release_survives_a_failing_reposition() -> None:
    """Even a restore that fails must not leave the user's aircraft frozen.

    The freeze context manager releases on its own ``finally``; the harness
    writes the release once more in its own — so a leaked
    ``override_planepath`` needs both to fail, not either.
    """
    boom = RuntimeError("scripted reposition failure")
    sim = ScriptedRestoreSim(final_state=restored_state(GROUND_HOME), reposition_error=boom)

    with pytest.raises(RuntimeError) as caught:
        await _restore_and_verify(sim, GROUND_HOME)
    assert caught.value is boom

    release = sim.index_of(FREEZE_RELEASE)
    hard_release = sim.index_of(("write", "override_planepath", 0, 0))
    assert release < hard_release
    # The post-condition verification never ran: the failure already reported.
    assert all(event[0] != "has_crashed" for event in sim.events)


# --------------------------------------------------------------------------
# The velocity the aircraft wakes up with
# --------------------------------------------------------------------------


async def test_a_ground_home_wakes_up_stationary() -> None:
    """An aircraft snapshotted on the ground is put back with zero velocity."""
    sim = ScriptedRestoreSim(final_state=restored_state(GROUND_HOME))
    await _restore_and_verify(sim, GROUND_HOME)

    velocities = [event for event in sim.events if event[0] == "velocity_vector"]
    assert velocities[-1] == ("velocity_vector", GROUND_HOME.heading_deg, 0.0)


async def test_an_airborne_home_wakes_up_level_at_its_own_speed() -> None:
    """An aircraft snapshotted flying gets its own IAS back, as TAS at home altitude.

    ``set_position`` alone would carry over whatever speed the *tests* ended
    at — the same class of wrong-speed handover as issue #39.
    """
    sim = ScriptedRestoreSim(final_state=restored_state(AIRBORNE_HOME))
    await _restore_and_verify(sim, AIRBORNE_HOME)

    conversion = sim.index_of(
        ("true_airspeed", AIRBORNE_HOME.ias_kt, AIRBORNE_HOME.position.altitude_ft)
    )
    handover = sim.index_of(
        ("velocity_vector", AIRBORNE_HOME.heading_deg, AIRBORNE_HOME.ias_kt * 1.1)
    )
    assert conversion < handover < sim.index_of(FREEZE_RELEASE)


# --------------------------------------------------------------------------
# The post-condition verification
# --------------------------------------------------------------------------


async def test_a_wrecked_aircraft_fails_the_run() -> None:
    sim = ScriptedRestoreSim(
        final_state=restored_state(GROUND_HOME),
        crashed_at_the_end=True,
    )
    with pytest.raises(RuntimeError, match="has_crashed"):
        await _restore_and_verify(sim, GROUND_HOME)


async def test_a_leaked_freeze_fails_the_run() -> None:
    sim = ScriptedRestoreSim(
        final_state=restored_state(GROUND_HOME),
        override_at_the_end=1,
    )
    with pytest.raises(RuntimeError, match="frozen"):
        await _restore_and_verify(sim, GROUND_HOME)


@pytest.mark.parametrize(
    "measured_roll",
    [
        pytest.param(179.80, id="inverted-2026-08-10-run-1"),
        pytest.param(91.62, id="wingtip-2026-08-10-run-2"),
    ],
)
async def test_the_attitudes_actually_measured_fail_the_run(measured_roll: float) -> None:
    """The two live wrecks this fix answers must never again pass silently."""
    sim = ScriptedRestoreSim(
        final_state=restored_state(GROUND_HOME, roll=measured_roll),
    )
    with pytest.raises(RuntimeError, match="attitude"):
        await _restore_and_verify(sim, GROUND_HOME)


async def test_settling_onto_the_gear_is_not_a_failure() -> None:
    """Single-digit residual pitch/roll is the aircraft sitting down, not a wreck.

    Guards the tolerance from being tightened into a teardown that fails every
    honest live run (see ``frozen_flight_model``: residual attitude after the
    release is physically correct).
    """
    sim = ScriptedRestoreSim(
        final_state=restored_state(GROUND_HOME, pitch=GROUND_HOME.pitch_deg + 3.0, roll=4.0),
    )
    await _restore_and_verify(sim, GROUND_HOME)


async def test_every_violation_is_reported_at_once() -> None:
    """A live failure report must show the whole picture, not the first symptom."""
    sim = ScriptedRestoreSim(
        final_state=restored_state(GROUND_HOME, roll=179.80),
        crashed_at_the_end=True,
        override_at_the_end=1,
    )
    with pytest.raises(RuntimeError) as caught:
        await _restore_and_verify(sim, GROUND_HOME)
    message = str(caught.value)
    assert "has_crashed" in message
    assert "frozen" in message
    assert "attitude" in message
