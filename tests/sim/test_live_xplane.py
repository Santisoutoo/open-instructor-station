"""End-to-end checks against a live X-Plane. Never runs in CI.

Run with a simulator loaded (on the ground or in the air) and its Web API
enabled::

    pytest -m sim

These tests move the user aircraft and put it back. Do not run them while
flying something you care about.
"""

import pytest

from adapters.xplane import XPlaneSimAdapter
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.local_frame import LocalCoordinates, world_to_local
from core.models import AircraftSetup, GeoPosition

pytestmark = pytest.mark.sim

TELEPORT_DISTANCE_NM = 5.0
#: Placement tolerance. Generous because the aircraft is flying by the time the
#: state is read back: at 100 kt a single second is already 51 m.
PLACEMENT_TOLERANCE_M = 400.0


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
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        origin = await adapter.measure_local_frame_origin()
        state = await adapter.get_aircraft_state()
        local = LocalCoordinates(
            x_m=float(await adapter.read_dataref("local_x")),
            y_m=float(await adapter.read_dataref("local_y")),
            z_m=float(await adapter.read_dataref("local_z")),
        )
        projected = world_to_local(
            origin,
            GeoPosition(
                latitude=state.latitude,
                longitude=state.longitude,
                altitude_ft=state.altitude_ft,
            ),
        )
        assert projected.x_m == pytest.approx(local.x_m, abs=1.0)
        assert projected.y_m == pytest.approx(local.y_m, abs=1.0)
        assert projected.z_m == pytest.approx(local.z_m, abs=1.0)
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
        before = await adapter.get_aircraft_state()
        await adapter.apply_setup(AircraftSetup(heading_deg=(before.heading_deg + 30.0) % 360.0))
        after = await adapter.get_aircraft_state()
        assert after.heading_deg == pytest.approx((before.heading_deg + 30.0) % 360.0, abs=5.0)
    finally:
        await adapter.disconnect()
