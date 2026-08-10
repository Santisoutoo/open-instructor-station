"""End-to-end checks against a live X-Plane. Never runs in CI.

Run with a simulator loaded (on the ground or in the air) and its Web API
enabled::

    pytest -m sim

These tests move the user aircraft and put it back. On top of that, the
session-scoped ``live_aircraft_home`` fixture in ``tests/conftest.py``
snapshots the aircraft before the first live test of the run and restores it
after the last, so ``pytest -m sim`` as a whole is position-neutral. Do not run
them while flying something you care about all the same.
"""

import asyncio

import pytest

from adapters.xplane import XPlaneSimAdapter
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.local_frame import LocalCoordinates, origin_separation_m, world_to_local
from core.models import AircraftSetup, GeoPosition

pytestmark = pytest.mark.sim

TELEPORT_DISTANCE_NM = 5.0
#: Placement tolerance. Generous because the aircraft is flying by the time the
#: state is read back: at 100 kt a single second is already 51 m.
PLACEMENT_TOLERANCE_M = 400.0

#: A hop far enough that X-Plane has to load new scenery and re-anchor its local
#: frame — the condition issue #36 is about. 400 NM is Madrid to well past the
#: Pyrenees, several frame-origin grid cells away; the reported case was Madrid
#: to Heathrow at ~675 NM.
LONG_HAUL_DISTANCE_NM = 400.0

#: Placement tolerance across a reload. Wider than :data:`PLACEMENT_TOLERANCE_M`
#: for one reason only: the read-back happens after the freeze is released, and
#: a reload pause is seconds rather than frames, so the aircraft has flown
#: further before anyone looks. Still four orders of magnitude tighter than the
#: failure being guarded against, which was the aircraft not arriving at all.
LONG_HAUL_TOLERANCE_M = 2000.0

#: How far the frame origin has to have moved for a long-haul run to count as
#: having exercised a relocation at all.
MINIMUM_FRAME_SHIFT_M = 100_000.0

#: X-Plane reports ``elevation`` in metres; the rest of the project is in feet.
METRES_PER_FOOT = 0.3048

#: Slack on the local frame's up axis when the two coordinate systems are read
#: back over several requests. See
#: :func:`test_local_frame_origin_reproduces_the_aircraft_position`.
VERTICAL_SAMPLING_TOLERANCE_M = 5.0


async def test_reads_a_plausible_state() -> None:
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        state = await adapter.get_aircraft_state()
        assert -90.0 <= state.latitude <= 90.0
        assert -180.0 <= state.longitude <= 180.0
        assert 0.0 <= state.heading_deg <= 360.0
        assert -2000.0 < state.altitude_ft < 60_000.0
    finally:
        await adapter.disconnect()


async def test_local_frame_origin_reproduces_the_aircraft_position() -> None:
    """The calibration that makes external repositioning possible.

    The origin is measured from the aircraft, not read from ``lat_ref``/
    ``lon_ref`` — those were observed to be wrong by ~200 km. Projecting the
    aircraft's own world position through the measured origin must reproduce
    the local coordinates the sim reports, to within float noise.

    **The aircraft is stopped first, and this is load-bearing.** The residual
    being asserted is a static geometric property, but it is assembled from six
    separate Web API reads, and the API serves each one from whichever frame
    happens to be current — there is no way to ask it for a consistent snapshot.
    A moving aircraft therefore slides between the reads, and the assertion
    silently measures that motion instead of the calibration: at 140 kt a
    handful of frames is already tens of metres, dwarfing the sub-metre residual
    this is looking for. Zeroing the velocity removes the noise rather than
    hiding it behind a loose tolerance.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        # Stop the aircraft so the six reads below describe one instant.
        # ``ias_kt`` is written through the velocity vector, which zeroes the
        # vertical component too, so this also arrests any inherited descent.
        await adapter.apply_setup(AircraftSetup(ias_kt=0.0))

        origin = await adapter.measure_local_frame_origin()
        keys = ("latitude", "longitude", "elevation", "local_x", "local_y", "local_z")
        raw = await asyncio.gather(*(adapter.read_dataref(key) for key in keys))
        sample = {key: float(value) for key, value in zip(keys, raw, strict=True)}

        local = LocalCoordinates(
            x_m=sample["local_x"],
            y_m=sample["local_y"],
            z_m=sample["local_z"],
        )
        projected = world_to_local(
            origin,
            GeoPosition(
                latitude=sample["latitude"],
                longitude=sample["longitude"],
                altitude_ft=sample["elevation"] / METRES_PER_FOOT,
            ),
        )
        # Horizontal: the axes a wrong frame origin blows up, and with the
        # aircraft stopped there is nothing left but float noise.
        assert projected.x_m == pytest.approx(local.x_m, abs=1.0)
        assert projected.z_m == pytest.approx(local.z_m, abs=1.0)
        # Vertical: gravity resumes the moment the velocity write lands, so the
        # up axis still absorbs the free fall accumulated across the sampling
        # window. A few frames of it is centimetres; the budget below is a wide
        # margin over that, and still four orders of magnitude tighter than the
        # 200 km error this test exists to catch.
        assert projected.y_m == pytest.approx(local.y_m, abs=VERTICAL_SAMPLING_TOLERANCE_M)
    finally:
        await adapter.disconnect()


async def test_teleports_five_nm_north_and_restores() -> None:
    """The key technical risk, exercised for real.

    Validated on X-Plane 12 at LEMD: placement exact, restore within 0.00 m.
    If repositioning stops working, ``set_position`` raises
    ``XPlaneRepositionFailed`` and this test fails loudly. That failure is the
    finding — do not skip it.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    before = await adapter.get_aircraft_state()
    home = GeoPosition(
        latitude=before.latitude,
        longitude=before.longitude,
        altitude_ft=before.altitude_ft,
    )
    try:
        target = point_at_distance_and_bearing(home, TELEPORT_DISTANCE_NM, 0.0)

        await adapter.set_position(target, heading_deg=before.heading_deg)
        after = await adapter.get_aircraft_state()
        moved = GeoPosition(latitude=after.latitude, longitude=after.longitude)

        travelled_nm, _ = distance_and_bearing(home, moved)
        assert travelled_nm == pytest.approx(TELEPORT_DISTANCE_NM, abs=0.5), (
            "the aircraft did not move to the requested position"
        )

        error_nm, _ = distance_and_bearing(moved, target)
        assert error_nm * METRES_PER_NAUTICAL_MILE <= PLACEMENT_TOLERANCE_M
    finally:
        # Always put the aircraft back where the user left it.
        await adapter.set_position(home, heading_deg=before.heading_deg)
        await adapter.disconnect()


async def test_teleports_across_a_scenery_reload_and_restores() -> None:
    """Issue #36 for real: a hop long enough to make X-Plane load new scenery.

    ``tests/adapters/test_xplane_scenery_reload.py`` proves the adapter re-aims
    when the frame origin moves, against a stand-in that relocates it on demand.
    What that stand-in cannot supply is X-Plane's own scheduler: when the reload
    fires relative to the write, how long the sim stops answering for, and where
    it re-anchors. This is the check that measures those.

    It is slow and it is disruptive by design — the simulator will pause while
    it loads, twice, because the aircraft is put back afterwards. That is the
    cost of the thing being tested, not a defect in the test.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    before = await adapter.get_aircraft_state()
    home = GeoPosition(
        latitude=before.latitude,
        longitude=before.longitude,
        altitude_ft=before.altitude_ft,
    )
    try:
        target = point_at_distance_and_bearing(home, LONG_HAUL_DISTANCE_NM, 0.0)

        origin_before = await adapter.measure_local_frame_origin()
        # Raises XPlaneRepositionFailed if it never converges, which is the
        # entire regression. Do not soften it.
        await adapter.set_position(target, heading_deg=before.heading_deg)
        after = await adapter.get_aircraft_state()
        origin_after = await adapter.measure_local_frame_origin()

        moved = GeoPosition(latitude=after.latitude, longitude=after.longitude)
        error_nm, _ = distance_and_bearing(moved, target)
        assert error_nm * METRES_PER_NAUTICAL_MILE <= LONG_HAUL_TOLERANCE_M

        # And the run has to have exercised the thing it exists for. If the
        # frame did not move, the placement above proved nothing about issue #36
        # and the hop needs to be longer — that is a finding about the test, not
        # a reason to let it pass quietly.
        shift_m = origin_separation_m(origin_before, origin_after)
        assert shift_m > MINIMUM_FRAME_SHIFT_M, (
            f"the local frame origin moved only {shift_m:.0f} m over "
            f"{LONG_HAUL_DISTANCE_NM:.0f} NM, so no scenery reload relocated it and this "
            "test did not exercise the convergence it is here for"
        )
    finally:
        await adapter.set_position(home, heading_deg=before.heading_deg)
        await adapter.disconnect()


async def test_teleport_does_not_leave_the_aircraft_wrecked() -> None:
    """X-Plane reads a position jump as an impact unless the procedure clears it.

    This is not cosmetic: a wrecked aircraft is unflyable, so an instructor
    repositioning a student mid-lesson would end the lesson. ``set_position``
    fires ``fix_all_systems`` as its last step precisely to prevent this.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    before = await adapter.get_aircraft_state()
    home = GeoPosition(
        latitude=before.latitude,
        longitude=before.longitude,
        altitude_ft=before.altitude_ft,
    )
    try:
        await adapter.clear_crash_state()
        assert await adapter.has_crashed() is False, "the aircraft was already wrecked"

        target = point_at_distance_and_bearing(home, TELEPORT_DISTANCE_NM, 0.0)
        await adapter.set_position(target, heading_deg=before.heading_deg)

        assert await adapter.has_crashed() is False
    finally:
        await adapter.set_position(home, heading_deg=before.heading_deg)
        await adapter.disconnect()


async def test_stream_state_delivers_live_updates() -> None:
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        stream = adapter.stream_state(0.25)
        states = []
        async for state in stream:
            states.append(state)
            if len(states) >= 3:
                break
        await stream.aclose()
        assert len(states) == 3
    finally:
        await adapter.disconnect()


async def test_apply_setup_writes_configuration() -> None:
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        # Read, write and read back inside one freeze: an airborne aircraft with
        # nobody flying it turns between the write and the read-back, which is
        # what made this assertion fail live (issue #48).
        async with adapter.frozen_flight_model():
            before = await adapter.get_aircraft_state()
            await adapter.apply_setup(
                AircraftSetup(heading_deg=(before.heading_deg + 30.0) % 360.0)
            )
            after = await adapter.get_aircraft_state()
        assert after.heading_deg == pytest.approx((before.heading_deg + 30.0) % 360.0, abs=5.0)
    finally:
        await adapter.disconnect()
