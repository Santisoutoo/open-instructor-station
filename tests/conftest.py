"""Shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

import pytest

from core.models import AircraftState, GeoPosition, Runway
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


#: Extra margin, in seconds, between the freeze coming off and
#: ``clear_crash_state``. The adapter already sleeps its own 1.0 s release
#: settle inside ``frozen_flight_model``; this is on top of it, because the
#: sim needs real time to register any impact the release provokes (the
#: aircraft settling onto its gear) *before* the crash state is cleared.
#: A ``fix_all_systems`` fired earlier than the impact clears the previous
#: crash and leaves the new one standing — exactly the wreck this restore
#: exists to prevent.
_RELEASE_SETTLE_S = 1.5

#: How far the restored pitch or roll may sit from the snapshot before the
#: restore refuses to call itself done, in degrees. Wide enough for the
#: aircraft settling onto its gear or a gust (single-digit degrees, physically
#: correct — see ``frozen_flight_model``); far below the failures actually
#: measured on 2026-08-10, which were 91.62° (on a wingtip) and 179.80°
#: (inverted).
_ATTITUDE_TOLERANCE_DEG = 20.0


@dataclass(frozen=True)
class LiveAircraftHome:
    """Where the user's aircraft was, and how it sat, before the suite ran."""

    position: GeoPosition
    heading_deg: float
    pitch_deg: float
    roll_deg: float
    ias_kt: float
    on_ground: bool


class LiveRestoreSim(Protocol):
    """The slice of ``XPlaneSimAdapter`` the session restore drives.

    A protocol rather than the concrete adapter so the restore *sequence* —
    the part of this harness that wrecked a real aircraft when it was wrong —
    is provable in CI against a scripted double (``tests/test_session_restore.py``)
    without a simulator. The private members are deliberate: the restore is
    test harness for the X-Plane adapter specifically, not application code
    going through ``SimAdapter``.
    """

    def frozen_flight_model(self) -> AbstractAsyncContextManager[None]: ...

    async def set_position(self, position: GeoPosition, heading_deg: float) -> None: ...

    async def clear_crash_state(self) -> None: ...

    async def has_crashed(self) -> bool: ...

    async def get_aircraft_state(self) -> AircraftState: ...

    async def _write(
        self, key: str, value: float | int | bool, index: int | None = None
    ) -> None: ...

    async def _read(self, key: str) -> Any: ...

    async def _true_airspeed_kt(self, ias_kt: float, altitude_ft: float | None = None) -> float: ...

    async def _write_velocity_vector(self, heading_deg: float, tas_kt: float) -> None: ...


async def _snapshot_live_aircraft() -> LiveAircraftHome:
    """Read the live aircraft's position, attitude and motion over a short connection."""
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
            ias_kt=state.ias_kt,
            on_ground=state.on_ground,
        )
    finally:
        await adapter.disconnect()


async def _restore_live_aircraft(home: LiveAircraftHome) -> None:
    """Open a short connection, restore the aircraft, verify, disconnect."""
    from adapters.xplane import XPlaneSimAdapter

    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        await _restore_and_verify(adapter, home)
    finally:
        await adapter.disconnect()


async def _restore_and_verify(adapter: LiveRestoreSim, home: LiveAircraftHome) -> None:
    """Put the live aircraft back where it was, upright, undamaged and unfrozen.

    The ordering here is the whole point, because getting it wrong is not
    hypothetical: on 2026-08-10 this restore put the aircraft back at ground
    level while it still believed it was descending at -3443 fpm, and fired
    ``clear_crash_state`` *before* that impact registered — so the crash it
    cleared was the old one, and the run ended with the user's aircraft
    inverted (roll 179.80°) and ``has_crashed`` true, under a green report.
    Hence, in order:

    1. **Motion dies first, inside the freeze.** The velocity vector and the
       indicated vertical speed are zeroed before the aircraft is put anywhere
       near the ground, so it cannot arrive mid-descent.
    2. **Position, attitude, then the wake-up velocity** — all inside the same
       (re-entrant, issue #48) freeze, because none of these writes stick
       against a running flight model (issue #37). The velocity written last is
       the one the aircraft wakes up with: stationary if it was on the ground,
       level at its own indicated speed if it was airborne — ``set_position``
       carries over whatever speed the *tests* ended at, which is exactly
       wrong here.
    3. **The freeze is released** (by ``frozen_flight_model``'s own
       ``finally``), and the sim gets :data:`_RELEASE_SETTLE_S` of real time
       for anything the release provokes — settling onto the gear — to play
       out and register.
    4. **Only then is the crash state cleared.** Nothing that could count as
       an impact may happen after this line.
    5. **A last unconditional override release runs in a ``finally``**, even if
       any of the above raised: the context manager already releases on its
       normal path, but its release write can itself be lost if the sim is
       mid-crash-reload, and a leaked ``override_planepath`` freezes the
       user's aircraft indefinitely. Redundant on the happy path, idempotent,
       and the difference between a red report and a frozen simulator on the
       sad one.

    Finally the restore **verifies its own post-condition** — not crashed, not
    frozen, attitude within :data:`_ATTITUDE_TOLERANCE_DEG` of the snapshot —
    and raises if the aircraft it is leaving behind is not the one it
    promised. A future regression in this ordering must fail the run, not
    silently wreck the user's session again.
    """
    try:
        async with adapter.frozen_flight_model():
            # 1. The aircraft must not believe it is moving — least of all
            #    descending — while it is being carried back to ground level.
            await adapter._write("local_vx", 0.0)
            await adapter._write("local_vy", 0.0)
            await adapter._write("local_vz", 0.0)
            await adapter._write("vh_ind_fpm", 0.0)
            # 2. Back to where it was. Re-entrant: runs inside this freeze.
            await adapter.set_position(home.position, heading_deg=home.heading_deg)
            await adapter._write("psi", home.heading_deg % 360.0)
            await adapter._write("theta", home.pitch_deg)
            await adapter._write("phi", home.roll_deg)
            # The velocity the aircraft wakes up with, overwriting the one
            # ``set_position`` carried over from wherever the tests left off.
            if home.on_ground:
                await adapter._write_velocity_vector(home.heading_deg, 0.0)
            else:
                tas_kt = await adapter._true_airspeed_kt(home.ias_kt, home.position.altitude_ft)
                await adapter._write_velocity_vector(home.heading_deg, tas_kt)
        # 3. Freeze released above; give the sim real time to settle and to
        #    register anything the release provoked.
        await asyncio.sleep(_RELEASE_SETTLE_S)
        # 4. Clear the crash state strictly after everything that could
        #    register as an impact.
        await adapter.clear_crash_state()
    finally:
        # 5. Whatever happened above, never leave the user's aircraft frozen.
        await adapter._write("override_planepath", 0, index=0)

    await _verify_live_aircraft_restored(adapter, home)


def _angle_error_deg(actual: float, expected: float) -> float:
    """Smallest absolute angular difference between two headings/attitudes."""
    return abs((actual - expected + 180.0) % 360.0 - 180.0)


async def _verify_live_aircraft_restored(adapter: LiveRestoreSim, home: LiveAircraftHome) -> None:
    """Fail the run loudly if the aircraft being left behind is not the one promised.

    Checks the three ways the 2026-08-10 sessions actually ended: wrecked
    (``has_crashed``), frozen (``override_planepath`` leaked), and knocked out
    of its attitude (inverted / on a wingtip). Raises with every violated
    condition, not just the first, so a live report shows the full picture.
    """
    problems: list[str] = []

    if await adapter.has_crashed():
        problems.append("has_crashed is true: the restore itself wrecked the aircraft")

    override = await adapter._read("override_planepath")
    engaged = override[0] if isinstance(override, list) else override
    if int(engaged) != 0:
        problems.append(f"override_planepath[0] is {engaged!r}: the flight model was left frozen")

    state = await adapter.get_aircraft_state()
    roll_error = _angle_error_deg(state.roll_deg, home.roll_deg)
    pitch_error = _angle_error_deg(state.pitch_deg, home.pitch_deg)
    if roll_error > _ATTITUDE_TOLERANCE_DEG or pitch_error > _ATTITUDE_TOLERANCE_DEG:
        problems.append(
            f"attitude is off by {pitch_error:.2f} deg pitch / {roll_error:.2f} deg roll "
            f"(now pitch {state.pitch_deg:.2f}, roll {state.roll_deg:.2f}; snapshot was "
            f"pitch {home.pitch_deg:.2f}, roll {home.roll_deg:.2f}, "
            f"tolerance {_ATTITUDE_TOLERANCE_DEG:.0f} deg)"
        )

    if problems:
        raise RuntimeError(
            "The session restore did not leave the user's aircraft the way it found it: "
            + "; ".join(problems)
            + ". The aircraft state above is what the user is now sitting in — "
            "fix the restore ordering in tests/conftest.py before trusting another live run."
        )


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
