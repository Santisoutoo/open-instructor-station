"""End-to-end checks against a live X-Plane. Never runs in CI.

Run with a simulator on the ground or in the air and its Web API enabled::

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
from core.models import AircraftSetup, GeoPosition

pytestmark = pytest.mark.sim

TELEPORT_DISTANCE_NM = 5.0


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


async def test_teleports_five_nm_north_and_restores() -> None:
    """The key technical risk, exercised for real.

    If repositioning over the Web API does not work, the adapter raises
    ``NotImplementedError`` pointing at the UDP ``VEHX`` fallback, and this
    test fails loudly. That failure is the finding — do not skip it.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        before = await adapter.get_aircraft_state()
        origin = GeoPosition(
            latitude=before.latitude,
            longitude=before.longitude,
            altitude_ft=before.altitude_ft,
        )
        target = point_at_distance_and_bearing(origin, TELEPORT_DISTANCE_NM, 0.0)

        await adapter.set_position(target, heading_deg=before.heading_deg)
        after = await adapter.get_aircraft_state()
        moved = GeoPosition(latitude=after.latitude, longitude=after.longitude)

        travelled_nm, _ = distance_and_bearing(origin, moved)
        assert travelled_nm == pytest.approx(TELEPORT_DISTANCE_NM, abs=0.5), (
            "the aircraft did not move to the requested position"
        )

        error_nm, _ = distance_and_bearing(moved, target)
        assert error_nm * METRES_PER_NAUTICAL_MILE <= 250.0
    finally:
        # Always put the aircraft back where the user left it.
        await adapter.set_position(
            GeoPosition(
                latitude=before.latitude,
                longitude=before.longitude,
                altitude_ft=before.altitude_ft,
            ),
            heading_deg=before.heading_deg,
        )
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
