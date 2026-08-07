"""Shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from core.models import GeoPosition, Runway
from server.deps import reset_adapter

if TYPE_CHECKING:
    from adapters.xplane import XPlaneSimAdapter

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


#: Seconds to let the sim register the freeze before writing through it, and to
#: let it settle after the release. Measured against X-Plane 12.4.3: one or two
#: physics frames is enough, these leave a wide margin.
_FREEZE_SETTLE_S = 0.3
_RELEASE_SETTLE_S = 1.5


@asynccontextmanager
async def frozen_flight_model(adapter: XPlaneSimAdapter) -> AsyncIterator[None]:
    """Freeze X-Plane's flight model for the duration of the block.

    **Attitude cannot be written into a live flight model.** Measured against a
    real X-Plane 12.4.3 at LEMD: writing ``psi``/``theta``/``phi`` while the
    model is running leaves the aircraft 7 degrees off a commanded heading in
    the mild case, 164 degrees off in the bad one, and — observed — inverted on
    the runway at ``roll = -180``. The same writes with the model frozen land
    exactly, and read back within 0.09 degrees once released.

    This is the same discipline ``XPlaneSimAdapter.set_position`` already
    applies to position writes (steps 1 and 4 of the five-step procedure in the
    adapter's module docstring). It is here in the tests rather than in the
    adapter because moving it into ``apply_setup`` is issue #37 — until that
    lands, this is what keeps the live suite's state setup honest.

    The release is in a ``finally`` on purpose: leaving ``override_planepath``
    engaged freezes the user's aircraft indefinitely.
    """
    await adapter._write("override_planepath", 1, index=0)
    try:
        await asyncio.sleep(_FREEZE_SETTLE_S)
        yield
    finally:
        await adapter._write("override_planepath", 0, index=0)


@dataclass(frozen=True)
class LiveAircraftHome:
    """Where the user's aircraft was, and how it sat, before the suite ran."""

    position: GeoPosition
    heading_deg: float
    pitch_deg: float
    roll_deg: float


async def _snapshot_live_aircraft() -> LiveAircraftHome:
    """Read the live aircraft's position and attitude over a short connection."""
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
            pitch_deg=state.pitch_deg,
            roll_deg=state.roll_deg,
        )
    finally:
        await adapter.disconnect()


async def _restore_live_aircraft(home: LiveAircraftHome) -> None:
    """Put the live aircraft back where it was, upright and undamaged.

    Restoring the position alone is not enough. A live run leaves the aircraft
    in whatever attitude it ended in, and ``apply_setup`` cannot correct that
    while the flight model is running (issue #37) — which is how a session was
    observed ending with the aircraft sitting inverted on the runway. The
    attitude is therefore written through :func:`frozen_flight_model`.
    """
    from adapters.xplane import XPlaneSimAdapter

    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        await adapter.set_position(home.position, heading_deg=home.heading_deg)
        async with frozen_flight_model(adapter):
            await adapter._write("psi", home.heading_deg % 360.0)
            await adapter._write("theta", home.pitch_deg)
            await adapter._write("phi", home.roll_deg)
        await asyncio.sleep(_RELEASE_SETTLE_S)
        # ``set_position`` already clears the crash state, but settling back
        # onto the gear after the release can trip it again. Cheap, idempotent.
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
