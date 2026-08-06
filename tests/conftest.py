"""Shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from core.models import GeoPosition, Runway
from server.deps import reset_adapter

#: A synthetic runway used across the geodesy tests: LEMD 32L-ish, pointing
#: north-west, at 2000 ft elevation so altitude maths is not masked by zero.
SAMPLE_RUNWAY = Runway(
    airport_icao="LEMD",
    ident="32L",
    threshold=GeoPosition(latitude=40.4700, longitude=-3.5700, altitude_ft=2000.0),
    true_bearing_deg=320.0,
    length_m=3500.0,
    elevation_ft=2000.0,
)

#: A runway pointing due true north, which makes traffic-pattern geometry
#: readable by eye: "left of the runway" is simply "to the west".
NORTH_RUNWAY = Runway(
    airport_icao="TEST",
    ident="36",
    threshold=GeoPosition(latitude=40.0000, longitude=-3.0000, altitude_ft=1000.0),
    true_bearing_deg=0.0,
    length_m=3000.0,
    elevation_ft=1000.0,
)


@pytest.fixture(autouse=True)
def _isolated_settings() -> Iterator[None]:
    """Make sure no test inherits another test's cached adapter or settings."""
    reset_adapter()
    yield
    reset_adapter()


# --------------------------------------------------------------------------
# Live simulator: leave the user's aircraft where we found it
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveAircraftHome:
    """Where the user's aircraft was before the suite started touching it."""

    position: GeoPosition
    heading_deg: float


async def _snapshot_live_aircraft() -> LiveAircraftHome:
    """Read the live aircraft's position over a short-lived connection."""
    from adapters.xplane import XPlaneSimAdapter

    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        state = await adapter.get_aircraft_state()
        return LiveAircraftHome(
            position=GeoPosition(
                latitude=state.latitude,
                longitude=state.longitude,
                altitude_ft=state.altitude_ft,
            ),
            heading_deg=state.heading_deg,
        )
    finally:
        await adapter.disconnect()


async def _restore_live_aircraft(home: LiveAircraftHome) -> None:
    """Put the live aircraft back, undamaged."""
    from adapters.xplane import XPlaneSimAdapter

    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        await adapter.set_position(home.position, heading_deg=home.heading_deg)
        # ``set_position`` already clears the crash state, but a run that ended
        # badly may have wrecked the aircraft some other way. Cheap, idempotent.
        await adapter.clear_crash_state()
    finally:
        await adapter.disconnect()


@pytest.fixture(scope="session", autouse=True)
def live_aircraft_home(request: pytest.FixtureRequest) -> Iterator[LiveAircraftHome | None]:
    """Snapshot the user's aircraft once per session, and put it back at the end.

    A real simulator remembers. Without this, ``pytest -m sim`` ends with the
    user's aircraft abandoned wherever the last test happened to drop it — the
    side effect ``docs/designs/live-contract-suite.md`` warned about.

    Snapshotting *once per session* rather than resetting before every test is
    deliberate: repositioning before all 22 contract tests was tried and
    reverted for being both slow and fragile. Per-test hygiene is handled by the
    non-teleporting stabilisation in ``tests/adapters/test_contract.py``.

    The fixture is autouse but inert unless live tests were actually collected,
    so CI never opens a socket. It yields ``None`` in that case.
    """
    if not any(item.get_closest_marker("sim") for item in request.session.items):
        yield None
        return

    # Run on a private event loop: this is session-scoped setup and teardown,
    # outside any per-test loop pytest-asyncio manages.
    home = asyncio.run(_snapshot_live_aircraft())
    try:
        yield home
    finally:
        asyncio.run(_restore_live_aircraft(home))
