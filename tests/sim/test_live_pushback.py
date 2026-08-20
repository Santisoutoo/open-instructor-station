"""Pushback against a live X-Plane. Never runs in CI.

``docs/designs/pushback-manager.md`` §8.3: what only a live simulator can
prove — that the computed chord actually lands where ``core.pushback`` says it
lands, that the nose really is rotated by the full angle, and that neither
leaves the aircraft somewhere the instructor did not ask for.

Run with a simulator loaded and its Web API enabled::

    pytest -m sim -k pushback

Every test restores the aircraft's position and heading in a ``finally``, and
the session-scoped ``live_aircraft_home`` fixture in ``tests/conftest.py``
snapshots the aircraft before the first live test of the run and puts it back
after the last, so ``pytest -m sim`` as a whole is position-neutral.

**These tests skip until the X-Plane adapter declares ``can_pushback``.**
``XPlaneSimAdapter.pushback()`` is the contract stub today — the flag flips
only once a live run proves the mapping, the same posture Phase 2 used for
weather, failures and fuel/payload (design §9.2, Track B). The skip is a
statement about the adapter, not a suppressed failure: the moment Track B
lands, this file is the run that judges it.
"""

from __future__ import annotations

import pytest

from adapters.xplane import XPlaneSimAdapter
from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.models import AircraftState, GeoPosition
from core.pushback import PushbackRequest, pushback_target
from core.sim_adapter import SimAdapter

pytestmark = pytest.mark.sim

#: How far the aircraft may end up from the computed chord, in metres. Mirrors
#: ``tests/adapters/test_contract.py::PUSHBACK_TOLERANCE_M["xplane"]``,
#: duplicated rather than imported so a test module never imports another test
#: module. Tighter than the general placement tolerance: the manoeuvre is short
#: and the aircraft is stationary at both ends, so there is no flight to absorb.
PUSHBACK_TOLERANCE_M = 5.0

#: Heading slack, in degrees — the same live tolerance the autopilot heading
#: tests already use. A frozen write reads back within a few tenths of a degree
#: (CLAUDE.md's attitude gotcha: 123.0° commanded, 123.19° measured).
HEADING_TOLERANCE_DEG = 1.0

#: A short push and a modest turn: enough to measure, small enough that the
#: aircraft cannot reach anything interesting on a ramp.
STRAIGHT_DISTANCE_M = 15.0
ARC_DISTANCE_M = 25.0
ARC_ANGLE_DEG = 60.0


def _position_of(state: AircraftState) -> GeoPosition:
    """The positional part of a state, as a target you can teleport back to."""
    return GeoPosition(
        latitude=state.latitude,
        longitude=state.longitude,
        altitude_ft=state.altitude_ft,
    )


async def _grounded_state(adapter: SimAdapter) -> AircraftState:
    """The live aircraft, settled on the ground — or a skip saying why not.

    A live simulator's ground state is whatever the user loaded. This asks it
    to settle by teleporting to its own current position at ``ias_kt=0`` (the
    already-validated ``set_position``) and skips with a clear reason if it
    still does not report ``on_ground`` — a live-only environmental
    precondition, stated rather than silently retried forever.
    """
    if not adapter.capabilities.can_pushback:
        pytest.skip(
            f"{adapter.name!r} does not declare can_pushback yet — the flag flips "
            "once this file's run proves the mapping (pushback-manager.md §9.2, Track B)."
        )

    state = await adapter.get_aircraft_state()
    if not state.on_ground and adapter.capabilities.can_set_position:
        await adapter.set_position(_position_of(state), heading_deg=state.heading_deg, ias_kt=0.0)
        state = await adapter.get_aircraft_state()
    if not state.on_ground:
        pytest.skip(
            "the aircraft did not settle on the ground — a live-sim environmental "
            "precondition for pushback, not a contract failure."
        )
    return state


async def test_straight_pushback_lands_on_the_computed_chord() -> None:
    """15 m straight back: the aircraft arrives where ``core.pushback`` said, nose held.

    The heading assertion is the one that catches a sign error in the velocity
    vector: a push that moved the aircraft correctly but swung it round would
    still satisfy the distance check.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        before = await _grounded_state(adapter)
        home = _position_of(before)
        request = PushbackRequest(direction="straight", distance_m=STRAIGHT_DISTANCE_M)
        expected = pushback_target(before, request)

        try:
            await adapter.pushback(request)
            after = await adapter.get_aircraft_state()

            error_nm, _bearing = distance_and_bearing(expected.position, _position_of(after))
            assert error_nm * METRES_PER_NAUTICAL_MILE <= PUSHBACK_TOLERANCE_M, (
                "the aircraft is not on the computed chord"
            )
            travelled_nm, bearing_deg = distance_and_bearing(home, _position_of(after))
            assert travelled_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(
                STRAIGHT_DISTANCE_M, abs=PUSHBACK_TOLERANCE_M
            )
            assert bearing_deg == pytest.approx((before.heading_deg + 180.0) % 360.0, abs=2.0), (
                "a straight push must travel along the back bearing"
            )
            assert after.heading_deg == pytest.approx(
                before.heading_deg, abs=HEADING_TOLERANCE_DEG
            ), "a straight push must not rotate the aircraft"
        finally:
            await adapter.set_position(home, heading_deg=before.heading_deg, ias_kt=0.0)
    finally:
        await adapter.disconnect()


async def test_arced_pushback_rotates_the_nose_by_the_full_angle() -> None:
    """25 m of arc, 60° to the right: D5's convention, measured for real.

    ``angle_deg`` is the TOTAL heading change, not a rate — so the read-back
    heading is exactly ``before + 60``, and the position is the chord that
    bisects the two tangents, not an arc length laid down in a straight line.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        before = await _grounded_state(adapter)
        home = _position_of(before)
        request = PushbackRequest(
            direction="right", distance_m=ARC_DISTANCE_M, angle_deg=ARC_ANGLE_DEG
        )
        expected = pushback_target(before, request)

        try:
            await adapter.pushback(request)
            after = await adapter.get_aircraft_state()

            assert after.heading_deg == pytest.approx(
                (before.heading_deg + ARC_ANGLE_DEG) % 360.0, abs=HEADING_TOLERANCE_DEG
            ), "'right' must rotate the nose clockwise by the full angle"
            error_nm, _bearing = distance_and_bearing(expected.position, _position_of(after))
            assert error_nm * METRES_PER_NAUTICAL_MILE <= PUSHBACK_TOLERANCE_M, (
                "the aircraft is not on the computed chord"
            )
        finally:
            await adapter.set_position(home, heading_deg=before.heading_deg, ias_kt=0.0)
    finally:
        await adapter.disconnect()
