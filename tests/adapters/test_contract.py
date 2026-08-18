"""THE ``SimAdapter`` contract suite.

Every adapter must pass every test here. ``FakeSimAdapter`` runs in CI; the
X-Plane adapter runs only under ``pytest -m sim`` against a live simulator.

**Extending the interface means extending this file.** ``CAPABILITY_COVERAGE``
below maps every flag on :class:`~core.sim_adapter.Capabilities` to the test
that pins its behaviour; :func:`test_every_capability_is_covered` fails as soon
as a flag is added without a decision about how it is tested.

**Writing a test that runs against a live simulator has three rules**, because
a simulator — unlike the Fake — is a single, shared, persistent thing:

1. *Never assume a starting state.* The ``adapter`` fixture stabilises the
   aircraft into level flight before every test, but where it is and what it is
   flying is whatever the user left loaded.
2. *Never use an absolute position or altitude.* Work relative to the
   aircraft's current state — see :data:`HOP_DISTANCE_NM`.
3. *Restore anything you move, in a ``finally``.* The session-scoped
   ``live_aircraft_home`` fixture is the safety net, not the plan.

The history behind those rules is in ``docs/designs/live-contract-suite.md``.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from adapters.fake import FakeSimAdapter
from core.failures import FAILURE_IDS, ActiveFailure, FailureRef
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.models import (
    AircraftSetup,
    AircraftState,
    AirframeInfo,
    AirframeMassLimits,
    CgEnvelope,
    CgEnvelopePoint,
    GeoPosition,
    LightsSetup,
    Loadout,
    LoadoutState,
    PayloadStation,
    TankFuel,
)
from core.sim_adapter import Capabilities, CapabilityNotSupported, SimAdapter
from core.weather.models import CloudLayer, WeatherSetup, WeatherState, WindLayer

# --------------------------------------------------------------------------
# Adapter parametrisation
# --------------------------------------------------------------------------

ADAPTER_PARAMS = [
    pytest.param("fake", id="fake"),
    pytest.param("xplane", id="xplane", marks=pytest.mark.sim),
]

#: How far a teleported aircraft may end up from its target, in metres. The
#: fake is exact; a live simulator keeps flying between the write and the
#: read-back. :data:`STABILISED_IAS_KT` is chosen to keep that drift well
#: inside this budget, so the number below has not had to move.
POSITION_TOLERANCE_M = {"fake": 1.0, "xplane": 250.0}

#: Stream tick used by the contract tests. Short enough to keep the suite fast,
#: long enough that a REST-polling adapter can keep up.
STREAM_INTERVAL_S = 0.05

#: How far the position tests move the aircraft, in nautical miles, measured
#: from wherever it already is.
#:
#: Every position test is **relative and self-restoring**. An absolute target is
#: a landmine against a live simulator: from an arbitrary starting position it
#: can turn into a transcontinental jump, and X-Plane relocates its local frame
#: origin during the scenery reload that provokes, so the read-back races the
#: loader. The contract under test is "the aircraft ends up where you asked" —
#: the distance is not part of it.
#:
#: The adapter now survives that relocation (issue #36) and this stayed short
#: anyway: convergence across a scenery reload is an X-Plane mechanic, not
#: something every adapter must implement, and it is pinned where it lives — in
#: ``tests/adapters/test_xplane_scenery_reload.py`` for CI and in
#: ``tests/sim/test_live_xplane.py`` for a real simulator. See
#: ``docs/designs/live-contract-suite.md``.
HOP_DISTANCE_NM = 5.0

#: Vertical displacement used by the tests that assert an altitude was written.
#: Relative, for the same reason as :data:`HOP_DISTANCE_NM`: an absolute MSL
#: altitude can be underground depending on where the user parked.
HOP_CLIMB_FT = 2000.0

#: Airspeed the aircraft is stabilised at before every contract test, in knots.
#: Fast enough that a stream tick moves it observably, slow enough that the
#: second or so a live simulator spends flying between a teleport and the
#: read-back stays comfortably inside :data:`POSITION_TOLERANCE_M`.
STABILISED_IAS_KT = 140.0

#: Speed a placement commands in :func:`test_set_position_delivers_the_commanded_speed`.
#: Well below :data:`STABILISED_IAS_KT` so "the commanded value" and "whatever the
#: aircraft happened to be doing" cannot be confused for one another — the bug this
#: pins read back 83 kt against 120 commanded (issue #39).
COMMANDED_IAS_KT = 90.0

#: Tolerance on that read-back. The Fake stores what it is handed; a live aircraft
#: is flying, and the freeze is released before the state is read.
COMMANDED_IAS_TOLERANCE_KT = {"fake": 0.1, "xplane": 15.0}

#: Vertical speed a placement commands in
#: :func:`test_set_position_delivers_the_vertical_speed`. A plausible 3°-final
#: descent rate — and clearly distinct from the level flight the ``adapter``
#: fixture stabilises into, so "delivered" and "whatever it was doing" cannot be
#: confused (the same construction as :data:`COMMANDED_IAS_KT`).
COMMANDED_VS_FPM = -600.0

#: Tolerance on that read-back. Both adapters are read while frozen against the
#: value the teleport *wrote* into the velocity vector, not the variometer of a
#: settling aeroplane, so the round-trip is near-exact on either side. (An
#: earlier version read ``vh_ind_fpm`` immediately after releasing the freeze
#: and needed ``xplane: 300.0`` to absorb the settling transient — which still
#: read the wrong sign when the aircraft entered the test from a disturbed
#: attitude, making the assertion flaky under full-suite ordering.)
COMMANDED_VS_TOLERANCE_FPM = {"fake": 0.1, "xplane": 5.0}

#: ``local_vy`` (the up axis of the velocity vector) is metres/second; the
#: contract speaks feet/minute. 60 s/min ÷ 0.3048 m/ft.
_FPM_PER_MS = 60.0 / 0.3048

#: Throttle :func:`test_apply_setup_delivers_the_throttle` commands. Approach
#: power — far from both idle and the full thrust a mis-read default would be.
COMMANDED_THROTTLE_RATIO = 0.3

#: How far a grounded aircraft is lifted before the tests run. Vertical only —
#: the horizontal position is untouched, so this never triggers a scenery
#: reload.
GROUND_CLEARANCE_FT = 1500.0

#: Per-adapter read-back tolerance for weather round-trips
#: (docs/designs/weather-manager.md §5.3). ``vis_ratio``/``coverage`` are
#: fractional; the tests turn them into an absolute tolerance against the
#: value under test.
WEATHER_READBACK_TOLERANCE: dict[str, dict[str, float]] = {
    "fake": {
        "dir_deg": 0.1,
        "speed_kt": 0.1,
        "vis_ratio": 0.001,
        "qnh_hpa": 0.1,
        "temp_c": 0.1,
        "base_ft": 1.0,
        "coverage": 0.01,
    },
    "xplane": {
        "dir_deg": 5.0,
        "speed_kt": 2.0,
        "vis_ratio": 0.10,
        "qnh_hpa": 1.0,
        "temp_c": 1.0,
        "base_ft": 250.0,
        "coverage": 0.15,
    },
}

#: How long a written weather value must hold before the read-back is
#: trusted. The ``xplane`` number must outlast the simulator's own
#: real-weather update cycle — roadmap Phase 2 exit criterion 3
#: (docs/designs/weather-manager.md §5.3 case 4, §11.5).
WEATHER_HOLD_S = {"fake": 0.2, "xplane": 90.0}

#: A live simulator's fuel-mass write/read round trip is not exact to the
#: gram; the Fake's is (docs/designs/fuel-payload.md §5.3).
LOADOUT_KG_TOLERANCE = {"fake": 0.01, "xplane": 1.0}

#: Which test pins each capability. ``PENDING`` marks a flag whose manager
#: arrives in a later phase: the contract is not written yet, and that is a
#: deliberate, visible decision rather than an oversight.
PENDING = "PENDING - contract arrives with the manager that implements it"

CAPABILITY_COVERAGE: dict[str, str] = {
    "can_set_position": "test_set_position_moves_the_aircraft",
    "can_set_aircraft_state": "test_apply_setup_applies_only_the_provided_fields",
    "can_set_weather": "test_set_weather_round_trips",
    "can_inject_failures": "test_injected_failure_is_reported_active",
    "can_spawn_traffic": PENDING,
    "can_control_autopilot": "test_apply_setup_writes_the_autopilot",
    "can_set_fuel_payload": "test_set_loadout_round_trips",
    "can_control_camera": PENDING,
    "can_pushback": PENDING,
}

#: Capability -> a setup carrying a field that capability gates. Used twice: to
#: prove an adapter that declares the flag accepts the fields, and to prove one
#: that does not refuses them outright instead of half-applying the setup.
#:
#: This is the machine-readable form of the rule in
#: :meth:`core.sim_adapter.SimAdapter.apply_setup`, so a field group added to
#: ``AircraftSetup`` under a new flag gets both halves of the contract for free.
CAPABILITY_GATED_SETUPS: dict[str, AircraftSetup] = {
    "can_control_autopilot": AircraftSetup(autopilot_master=True),
    "can_set_fuel_payload": AircraftSetup(
        gross_weight_kg=60_000.0,
        loadout=Loadout(tanks=[TankFuel(tank_index=0, fuel_kg=100.0)]),
    ),
}


def _build(name: str) -> SimAdapter:
    """Construct an adapter by name without importing X-Plane's client in CI."""
    if name == "fake":
        return FakeSimAdapter()
    if name == "xplane":
        from adapters.xplane import XPlaneSimAdapter

        return XPlaneSimAdapter()
    raise ValueError(f"Unknown adapter {name!r}")


async def _stabilise(adapter: SimAdapter) -> None:
    """Put the aircraft into a known, level, flying state — without teleporting it.

    ``FakeSimAdapter`` is constructed fresh for every test; a real simulator is
    not. Each live test therefore inherits whatever the previous one left
    behind, commonly an aircraft in free fall. This levels the attitude and
    rewrites the velocity vector — which zeroes the vertical component, so free
    fall stops — and lifts the aircraft clear of the ground only when it is
    actually on it. A parked aircraft will not accelerate no matter what
    velocity is written to it, so leaving it there would test the environment
    rather than the adapter.

    It deliberately does **not** reposition. Teleporting before every test was
    tried and reverted: see ``docs/designs/live-contract-suite.md``. This costs
    a handful of writes and no settle time.

    It runs for every adapter, not just the live one, so CI exercises it too.
    """
    if not adapter.capabilities.can_set_aircraft_state:
        return
    state = await adapter.get_aircraft_state()
    await adapter.apply_setup(
        AircraftSetup(
            altitude_ft=state.altitude_ft + GROUND_CLEARANCE_FT if state.on_ground else None,
            heading_deg=state.heading_deg,
            pitch_deg=0.0,
            roll_deg=0.0,
            ias_kt=STABILISED_IAS_KT,
        )
    )


@asynccontextmanager
async def _frozen_for_readback(adapter: SimAdapter) -> AsyncIterator[None]:
    """Hold the aircraft still so a read-back measures the write, not later flight.

    ``_stabilise`` deliberately leaves a live aircraft airborne at
    :data:`STABILISED_IAS_KT` with nobody flying it, so between a write and the
    read-back that verifies it the aeroplane keeps going: heading errors of 4°
    to 170° were measured against X-Plane, far outside the 1° the assertions
    allow (issue #48). Writing *and* reading inside one freeze makes the
    read-back a measurement of the adapter instead of a measurement of a second
    of uncommanded flight.

    Discovered by duck typing rather than through :class:`SimAdapter`: freezing
    a flight model is an X-Plane mechanic and has no place in the sim-agnostic
    seam. Same precedent as the Fake-only ``applied_setup`` affordance. An
    adapter without the method needs no freeze — the Fake has no flight model,
    so its state does not move between calls.
    """
    freeze = getattr(adapter, "frozen_flight_model", None)
    if freeze is None:
        yield
        return
    async with freeze():
        yield


@pytest.fixture(params=ADAPTER_PARAMS)
async def adapter(request: pytest.FixtureRequest) -> AsyncIterator[SimAdapter]:
    """A connected, stabilised adapter, disconnected again when the test finishes.

    The ``xplane`` parametrisation drives a simulator that carries state across
    tests, so :func:`_stabilise` gives every test the same starting conditions
    without the cost of a teleport. Whatever position the run started from is
    snapshotted and restored once by the session-scoped ``live_aircraft_home``
    fixture in ``tests/conftest.py``; tests that need a *specific* position set
    it themselves and put it back in a ``finally``.
    """
    instance = _build(request.param)
    await instance.connect()
    try:
        await _stabilise(instance)
        yield instance
    finally:
        await instance.disconnect()


def _position_of(state: AircraftState) -> GeoPosition:
    """The positional part of a state, as a target you can teleport back to."""
    return GeoPosition(
        latitude=state.latitude,
        longitude=state.longitude,
        altitude_ft=state.altitude_ft,
    )


async def _take(stream: AsyncIterator[AircraftState], count: int) -> list[AircraftState]:
    """Pull ``count`` states off a stream, then close it."""
    collected: list[AircraftState] = []
    try:
        async for state in stream:
            collected.append(state)
            if len(collected) >= count:
                break
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()
    return collected


# --------------------------------------------------------------------------
# Structure of the contract itself
# --------------------------------------------------------------------------


def test_every_capability_is_covered() -> None:
    """Adding a capability flag must mean adding a case to this suite."""
    declared = set(Capabilities.model_fields)
    covered = set(CAPABILITY_COVERAGE)
    assert declared == covered, (
        "Capabilities and CAPABILITY_COVERAGE have drifted apart. "
        f"Uncovered: {sorted(declared - covered)}; stale: {sorted(covered - declared)}."
    )


def test_covered_capabilities_name_real_tests() -> None:
    """Every non-pending coverage entry must point at a test in this module."""
    module_tests = {name for name in globals() if name.startswith("test_")}
    for capability, test_name in CAPABILITY_COVERAGE.items():
        if test_name == PENDING:
            continue
        assert test_name in module_tests, f"{capability} points at missing test {test_name!r}"


def test_fake_adapter_declares_every_capability() -> None:
    """The reference implementation supports everything, by definition."""
    capabilities = FakeSimAdapter().capabilities
    missing = [flag for flag in Capabilities.model_fields if not getattr(capabilities, flag)]
    assert missing == [], f"FakeSimAdapter must implement every capability; missing {missing}"


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


async def test_connects_and_reports_it(adapter: SimAdapter) -> None:
    assert adapter.is_connected is True


async def test_has_a_name(adapter: SimAdapter) -> None:
    assert isinstance(adapter.name, str)
    assert adapter.name


async def test_satisfies_the_protocol_at_runtime(adapter: SimAdapter) -> None:
    assert isinstance(adapter, SimAdapter)


async def test_connect_is_idempotent(adapter: SimAdapter) -> None:
    await adapter.connect()
    assert adapter.is_connected is True


async def test_disconnect_is_idempotent(adapter: SimAdapter) -> None:
    await adapter.disconnect()
    await adapter.disconnect()
    assert adapter.is_connected is False


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------


async def test_declares_capabilities(adapter: SimAdapter) -> None:
    assert isinstance(adapter.capabilities, Capabilities)


async def test_capabilities_are_stable(adapter: SimAdapter) -> None:
    """Capabilities are a static declaration, not runtime state."""
    first = adapter.capabilities
    assert adapter.capabilities == first


async def test_capabilities_are_immutable(adapter: SimAdapter) -> None:
    """Nothing may talk an adapter into claiming a capability it lacks."""
    capabilities = adapter.capabilities
    with pytest.raises(ValidationError):
        capabilities.can_set_weather = True


# --------------------------------------------------------------------------
# Reading state
# --------------------------------------------------------------------------


async def test_get_aircraft_state_returns_a_valid_state(adapter: SimAdapter) -> None:
    state = await adapter.get_aircraft_state()
    assert isinstance(state, AircraftState)
    assert -90.0 <= state.latitude <= 90.0
    assert -180.0 <= state.longitude <= 180.0
    assert 0.0 <= state.heading_deg <= 360.0
    assert state.ias_kt >= 0.0
    assert -90.0 <= state.pitch_deg <= 90.0
    assert -180.0 <= state.roll_deg <= 180.0
    assert isinstance(state.on_ground, bool)


# --------------------------------------------------------------------------
# can_set_position
# --------------------------------------------------------------------------


async def test_set_position_moves_the_aircraft(adapter: SimAdapter) -> None:
    """Teleport, then read back: the aircraft must actually be there.

    The hop is short and measured from wherever the aircraft already is, and it
    is undone in ``finally`` — see :data:`HOP_DISTANCE_NM` for why an absolute
    target is the wrong shape for this assertion. The teleport and the read-back
    share one freeze (:func:`_frozen_for_readback`); the restore is outside it.
    """
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    target = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 0.0)
    try:
        async with _frozen_for_readback(adapter):
            await adapter.set_position(target, heading_deg=270.0)
            moved = await adapter.get_aircraft_state()
        here = GeoPosition(latitude=moved.latitude, longitude=moved.longitude)
        error_nm, _ = distance_and_bearing(here, target)
        assert error_nm * METRES_PER_NAUTICAL_MILE <= POSITION_TOLERANCE_M[adapter.name]
        assert moved.heading_deg == pytest.approx(270.0, abs=1.0)
    finally:
        await adapter.set_position(home, heading_deg=original.heading_deg)


async def test_set_position_sets_the_altitude(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    horizontal = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 90.0)
    target = GeoPosition(
        latitude=horizontal.latitude,
        longitude=horizontal.longitude,
        altitude_ft=original.altitude_ft + HOP_CLIMB_FT,
    )
    try:
        await adapter.set_position(target, heading_deg=90.0)
        state = await adapter.get_aircraft_state()
        assert state.altitude_ft == pytest.approx(target.altitude_ft, abs=100.0)
    finally:
        await adapter.set_position(home, heading_deg=original.heading_deg)


async def test_set_position_delivers_the_commanded_speed(adapter: SimAdapter) -> None:
    """A commanded ``ias_kt`` must arrive, not be quietly replaced by the current one.

    The failure this pins is not a refusal — it is a faithful preservation of the
    wrong number. A placement applies its setup, the flight model is released, the
    aircraft decelerates while it settles, and an adapter that reads the speed for
    itself carries the decayed value onto the new heading: 120 kt commanded, 83 kt
    measured at LEMD (issue #39). Only a read-back can tell the two apart.
    """
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    target = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 45.0)
    try:
        await adapter.set_position(target, heading_deg=45.0, ias_kt=COMMANDED_IAS_KT)
        state = await adapter.get_aircraft_state()
        assert state.ias_kt == pytest.approx(
            COMMANDED_IAS_KT, abs=COMMANDED_IAS_TOLERANCE_KT[adapter.name]
        )
    finally:
        await adapter.set_position(home, heading_deg=original.heading_deg)


#: Bound on how long a fresh teleport's *indicated* airspeed takes to settle
#: once a non-zero wind is also freshly written, per
#: :func:`test_set_position_delivers_the_commanded_speed_with_wind`. Measured
#: live: the ground-velocity vector written is correct *immediately* (its own
#: raw local_vx/vy/vz read back matching the predicted TAS-minus-headwind
#: ground speed on the first read after the teleport) — what lags is
#: X-Plane's own derivation of the indicated-airspeed instrument from that
#: ground velocity plus the freshly-set regional wind, taking anywhere from
#: ~3s to ~10s+ across repeated runs to settle within tolerance. This is a
#: genuine instrument-settling effect, the same category as
#: :data:`COMMANDED_IAS_TOLERANCE_KT`'s own "released the freeze, aircraft is
#: still settling" note — just slower here because a fresh wind is also
#: involved, not a defect in the write.
_WIND_IAS_SETTLE_TIMEOUT_S = 20.0
_WIND_IAS_SETTLE_POLL_INTERVAL_S = 1.0


async def test_set_position_delivers_the_commanded_speed_with_wind(adapter: SimAdapter) -> None:
    """Issue #42's own acceptance criterion: the commanded IAS is achieved
    with a non-zero wind set, verified against a live simulator — a still-air
    test (see :func:`test_set_position_delivers_the_commanded_speed` above)
    cannot detect this bug at all.

    A strong (25 kt) direct headwind is set at the aircraft's own altitude,
    and the target heading points straight into it. If the ground-velocity
    vector were still written air-relative (the pre-#42 bug: the vector
    X-Plane consumes is a *ground* velocity, only equal to the air-relative
    one in still air), the read-back would settle roughly 25 kt short of what
    was commanded and never enter tolerance no matter how long this polls —
    comfortably outside :data:`COMMANDED_IAS_TOLERANCE_KT`, so a regression in
    the wind subtraction fails this test loudly, not by a marginal amount.
    """
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")
    if not adapter.capabilities.can_set_weather:
        pytest.skip(f"{adapter.name} does not declare can_set_weather")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    heading_deg = 0.0
    target = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, heading_deg)

    wind_direction_deg = heading_deg  # wind FROM the north == a direct headwind on heading 0.
    try:
        await adapter.set_weather(
            WeatherSetup(
                wind_layers=[
                    WindLayer(
                        altitude_ft=max(0.0, original.altitude_ft),
                        direction_deg=wind_direction_deg,
                        speed_kt=25.0,
                    )
                ]
            )
        )
        await adapter.set_position(target, heading_deg=heading_deg, ias_kt=COMMANDED_IAS_KT)

        tol = COMMANDED_IAS_TOLERANCE_KT[adapter.name]
        deadline = asyncio.get_running_loop().time() + _WIND_IAS_SETTLE_TIMEOUT_S
        state = await adapter.get_aircraft_state()
        while (
            abs(state.ias_kt - COMMANDED_IAS_KT) > tol
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(_WIND_IAS_SETTLE_POLL_INTERVAL_S)
            state = await adapter.get_aircraft_state()
        assert state.ias_kt == pytest.approx(COMMANDED_IAS_KT, abs=tol)
    finally:
        await adapter.set_position(home, heading_deg=original.heading_deg)
        await adapter.set_weather(WeatherSetup(wind_layers=[]))


async def test_set_position_without_a_speed_preserves_the_current_one(
    adapter: SimAdapter,
) -> None:
    """The other half of the contract: ``None`` means "carry what it has".

    This is what moving an already-flying aeroplane wants, and it is the default,
    so it has to keep working after the commanded case was added.
    """
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    target = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 135.0)
    try:
        await adapter.set_position(target, heading_deg=135.0)
        state = await adapter.get_aircraft_state()
        assert state.ias_kt == pytest.approx(
            original.ias_kt, abs=COMMANDED_IAS_TOLERANCE_KT[adapter.name]
        )
    finally:
        await adapter.set_position(home, heading_deg=original.heading_deg)


async def test_set_position_delivers_the_vertical_speed(adapter: SimAdapter) -> None:
    """A commanded ``vertical_speed_fpm`` must arrive; ``None`` must arrive level.

    The vertical twin of :func:`test_set_position_delivers_the_commanded_speed`
    (issue #81): the velocity vector a teleport writes is the whole velocity,
    and an adapter that hard-codes its vertical component to zero destroys the
    descent a setup commanded one call later — every 3° final used to arrive in
    level flight regardless of what was asked.

    What is asserted is the vertical component the teleport *wrote into the
    velocity vector*, read back while the flight model is still frozen — not the
    variometer. A frozen model does not integrate, so the vector is exactly what
    ``set_position`` set and the read is deterministic. Reading ``vh_ind_fpm``
    immediately after releasing the freeze instead (the previous approach) was
    flaky under full-suite ordering: from a disturbed entry attitude the ~1 s of
    unpiloted settling could swamp the commanded rate and even flip its sign
    (issue #12 live run, 2026-08-14). On a live adapter the written component is
    ``local_vy`` (metres/second, up), reached through ``read_dataref`` — the
    same duck-typing the autopilot None-contract test uses (issue #83); the Fake
    mirrors the commanded rate in its aircraft state.
    """
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    horizontal = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 225.0)
    # Climb before descending: the commanded descent must have room below it.
    target = GeoPosition(
        latitude=horizontal.latitude,
        longitude=horizontal.longitude,
        altitude_ft=original.altitude_ft + HOP_CLIMB_FT,
    )
    read = getattr(adapter, "read_dataref", None)
    try:
        async with _frozen_for_readback(adapter):
            await adapter.set_position(
                target,
                heading_deg=225.0,
                ias_kt=COMMANDED_IAS_KT,
                vertical_speed_fpm=COMMANDED_VS_FPM,
            )
            if read is not None:
                delivered_fpm = float(await read("local_vy")) * _FPM_PER_MS
            else:
                delivered_fpm = (await adapter.get_aircraft_state()).vertical_speed_fpm
        assert delivered_fpm == pytest.approx(
            COMMANDED_VS_FPM, abs=COMMANDED_VS_TOLERANCE_FPM[adapter.name]
        )
    finally:
        await adapter.set_position(home, heading_deg=original.heading_deg)


async def test_set_position_normalises_the_heading(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    target = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 180.0)
    try:
        async with _frozen_for_readback(adapter):
            await adapter.set_position(target, heading_deg=450.0)
            state = await adapter.get_aircraft_state()
        assert 0.0 <= state.heading_deg <= 360.0
        assert state.heading_deg == pytest.approx(90.0, abs=1.0)
    finally:
        await adapter.set_position(home, heading_deg=original.heading_deg)


# --------------------------------------------------------------------------
# can_set_aircraft_state
# --------------------------------------------------------------------------


async def test_apply_setup_applies_only_the_provided_fields(adapter: SimAdapter) -> None:
    """Set fields are applied; ``None`` fields are left exactly as they were.

    The target altitude is relative to where the aircraft is. Against a live
    simulator that matters twice over: an absolute MSL altitude can be
    underground, and the ``adapter`` fixture has just arrested any inherited
    free fall, so the 100 ft window measures the write rather than the seconds
    of descent that used to happen between it and the read-back.

    The whole before/apply/after sequence runs inside one freeze: the
    ``roll_deg`` assertion compares two reads, so both of them have to be taken
    off an aircraft that is not flying between them (issue #48).
    """
    if not adapter.capabilities.can_set_aircraft_state:
        pytest.skip(f"{adapter.name} does not declare can_set_aircraft_state")

    async with _frozen_for_readback(adapter):
        before = await adapter.get_aircraft_state()
        target_altitude_ft = before.altitude_ft + HOP_CLIMB_FT
        await adapter.apply_setup(
            AircraftSetup(altitude_ft=target_altitude_ft, heading_deg=123.0, pitch_deg=4.0)
        )
        after = await adapter.get_aircraft_state()

    # Provided fields moved.
    assert after.altitude_ft == pytest.approx(target_altitude_ft, abs=100.0)
    assert after.heading_deg == pytest.approx(123.0, abs=1.0)
    assert after.pitch_deg == pytest.approx(4.0, abs=1.0)
    # Fields left as None were not touched.
    assert after.roll_deg == pytest.approx(before.roll_deg, abs=1.0)


async def test_apply_setup_with_nothing_set_changes_nothing(adapter: SimAdapter) -> None:
    """An empty setup writes nothing, so the two reads must agree.

    Frozen for the same reason as the test above: nothing is written here, and
    the difference the assertions were catching live was simply the aircraft
    flying between the ``before`` read and the ``after`` one (issue #48).
    """
    if not adapter.capabilities.can_set_aircraft_state:
        pytest.skip(f"{adapter.name} does not declare can_set_aircraft_state")
    async with _frozen_for_readback(adapter):
        before = await adapter.get_aircraft_state()
        await adapter.apply_setup(AircraftSetup())
        after = await adapter.get_aircraft_state()
    assert after.altitude_ft == pytest.approx(before.altitude_ft, abs=100.0)
    assert after.heading_deg == pytest.approx(before.heading_deg, abs=1.0)


async def test_apply_setup_normalises_the_heading(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_set_aircraft_state:
        pytest.skip(f"{adapter.name} does not declare can_set_aircraft_state")
    await adapter.apply_setup(AircraftSetup(heading_deg=360.0))
    state = await adapter.get_aircraft_state()
    assert 0.0 <= state.heading_deg <= 360.0


async def test_apply_setup_delivers_the_throttle(adapter: SimAdapter) -> None:
    """``throttle_ratio`` is aircraft state and rides ``apply_setup`` like flaps.

    New in the pre-teleport-setup contract (issue #81: an aircraft placed on a
    final with parked throttle diverges into a phugoid). The Fake proves the
    value is recorded; a live adapter proves the write landed by reading the
    dataref back — and puts the levers back where they were, because a throttle
    moved mid-suite changes what every later test's aircraft is doing.
    """
    if not adapter.capabilities.can_set_aircraft_state:
        pytest.skip(f"{adapter.name} does not declare can_set_aircraft_state")

    read = getattr(adapter, "read_dataref", None)
    original = None if read is None else float(await read("throttle_ratio"))
    try:
        await adapter.apply_setup(AircraftSetup(throttle_ratio=COMMANDED_THROTTLE_RATIO))

        applied = getattr(adapter, "applied_setup", None)
        if applied is not None:
            assert applied.throttle_ratio == pytest.approx(COMMANDED_THROTTLE_RATIO)
        if read is not None:
            assert float(await read("throttle_ratio")) == pytest.approx(
                COMMANDED_THROTTLE_RATIO, abs=0.05
            )
    finally:
        if original is not None:
            await adapter.apply_setup(AircraftSetup(throttle_ratio=original))


async def test_apply_setup_refuses_capability_gated_fields_it_cannot_honour(
    adapter: SimAdapter,
) -> None:
    """Hard rule 3 at the adapter seam: refuse the whole call, never half-apply it.

    A field group an adapter cannot honour must come back as
    :class:`CapabilityNotSupported` — the caller ignored the flags, and that is a
    bug in the caller rather than something to silently drop. The X-Plane adapter
    is the live example: it drives an autopilot but cannot set mass or fuel.
    """
    undeclared = {
        capability: setup
        for capability, setup in CAPABILITY_GATED_SETUPS.items()
        if not getattr(adapter.capabilities, capability)
    }
    if not undeclared:
        pytest.skip(f"{adapter.name} declares every capability-gated field group")

    for capability, setup in undeclared.items():
        with pytest.raises(CapabilityNotSupported, match=capability):
            await adapter.apply_setup(setup)


# --------------------------------------------------------------------------
# can_control_autopilot
# --------------------------------------------------------------------------


async def test_apply_setup_writes_the_autopilot(adapter: SimAdapter) -> None:
    """The autopilot rides on ``apply_setup``; this is the contract that says so.

    There is deliberately no ``set_autopilot`` on :class:`SimAdapter` (issue
    #41): arming a mode and dialling the selector it flies to is one instructor
    intent, so it is one call, gated by ``can_control_autopilot``.

    **The servos are deliberately not engaged here.** Against a live simulator
    this test would otherwise hand an aeroplane to an autopilot mid-suite and
    fly it away from every subsequent test's assumptions. What it writes instead
    is inert: selector values, and a lateral mode that does nothing while the
    servos are off. The master/flight-director ladder is a pure fold over
    X-Plane's three-valued mode and is pinned in
    ``tests/adapters/test_xplane_autopilot.py`` instead.

    The selectors are relative to where the aircraft is, for the same reason
    every position test is — see :data:`HOP_DISTANCE_NM`.
    """
    if not adapter.capabilities.can_control_autopilot:
        pytest.skip(f"{adapter.name} does not declare can_control_autopilot")

    state = await adapter.get_aircraft_state()
    target_altitude_ft = state.altitude_ft + HOP_CLIMB_FT
    setup = AircraftSetup(
        autopilot_hdg=True,
        target_altitude_ft=target_altitude_ft,
        target_ias_kt=STABILISED_IAS_KT,
        target_heading_deg=(state.heading_deg + 10.0) % 360.0,
        target_vertical_speed_fpm=500.0,
    )
    try:
        # Accepting the write is itself the assertion for an adapter that talks
        # to a simulator: a selector X-Plane will not take comes back as an HTTP
        # error, not as a shrug.
        await adapter.apply_setup(setup)

        applied = getattr(adapter, "applied_setup", None)
        if applied is not None:
            assert applied.autopilot_hdg is True
            assert applied.target_altitude_ft == pytest.approx(target_altitude_ft)
            assert applied.target_ias_kt == pytest.approx(STABILISED_IAS_KT)
            assert applied.target_vertical_speed_fpm == pytest.approx(500.0)
    finally:
        # Wing-leveller is the neutral lateral mode; there is no per-mode
        # "off" to restore to, because the modes are mutually exclusive.
        await adapter.apply_setup(AircraftSetup(autopilot_hdg=False))


async def test_apply_setup_leaves_the_autopilot_alone_when_asked_for_nothing(
    adapter: SimAdapter,
) -> None:
    """``None`` on an autopilot field means *do not touch that switch*.

    Worth its own test because the failure mode is invisible: a writer that read
    ``None`` as "off" would silently disarm a mode the instructor never mentioned
    every time an unrelated control was written.

    Two duck-typed read-backs verify it, and one of them must exist (issue #83 —
    this test used to ``skip`` itself against a live adapter, which left the
    contract verified only by the Fake agreeing with itself):

    * The Fake records what was applied; ``applied_setup`` shows the fields the
      setup never mentioned still ``None``.
    * A live adapter exposes ``read_dataref`` (the same duck-typing precedent as
      :func:`_frozen_for_readback` and the throttle test): the four autopilot
      values the setup does not carry are snapshotted before the write and must
      read back unchanged after it — while the heading dial, the one field it
      *does* carry, must have moved, or the four "unchanged" assertions prove
      nothing. The write is deliberately inert — a heading dial with no servos
      engaged flies nobody anywhere — and the dial goes back in a ``finally``
      (live-suite rule 3).

    An adapter exposing neither affordance **fails** this test outright, never
    skips: a skip here is exactly how the gap stayed hidden.
    """
    if not adapter.capabilities.can_control_autopilot:
        pytest.skip(f"{adapter.name} does not declare can_control_autopilot")

    read = getattr(adapter, "read_dataref", None)
    if read is None:
        await adapter.apply_setup(AircraftSetup(target_heading_deg=90.0))

        applied = getattr(adapter, "applied_setup", None)
        if applied is None:
            pytest.fail(
                f"{adapter.name} exposes neither `applied_setup` nor `read_dataref`, "
                "so the autopilot None-contract cannot be verified against it. Give "
                "the adapter a read-back affordance — skipping here is how this gap "
                "went unverified in the first place (issue #83)."
            )
        assert applied.target_heading_deg == pytest.approx(90.0)
        assert applied.autopilot_master is None
        assert applied.autopilot_nav is None
        assert applied.flight_director is None
        return

    untouched_keys = (
        "autopilot_mode",
        "autopilot_altitude_dial_ft",
        "autopilot_airspeed_dial",
        "autopilot_vvi_dial_fpm",
    )
    before = {key: float(await read(key)) for key in untouched_keys}
    original_heading = float(await read("autopilot_heading_dial_deg"))
    # The target must provably differ from where the dial already sits, or
    # "changed" is not observable. The dial reads back in magnetic degrees.
    target_heading = 90.0 if abs(original_heading - 90.0) > 5.0 else 180.0
    try:
        await adapter.apply_setup(AircraftSetup(target_heading_deg=target_heading))

        after = {key: float(await read(key)) for key in untouched_keys}
        assert after["autopilot_mode"] == before["autopilot_mode"]
        assert after["autopilot_altitude_dial_ft"] == pytest.approx(
            before["autopilot_altitude_dial_ft"]
        )
        assert after["autopilot_airspeed_dial"] == pytest.approx(before["autopilot_airspeed_dial"])
        assert after["autopilot_vvi_dial_fpm"] == pytest.approx(before["autopilot_vvi_dial_fpm"])
        # The one field the setup did carry must have landed.
        assert float(await read("autopilot_heading_dial_deg")) == pytest.approx(
            target_heading, abs=0.5
        )
    finally:
        await adapter.apply_setup(AircraftSetup(target_heading_deg=original_heading))


# --------------------------------------------------------------------------
# can_set_weather
# --------------------------------------------------------------------------

#: A full, distinctive setup — every scalar and every layer field is a value
#: that could not be confused with a default, per weather-manager.md §5.3
#: case 1.
_DISTINCTIVE_WEATHER = WeatherSetup(
    wind_layers=[
        WindLayer(altitude_ft=0.0, direction_deg=200.0, speed_kt=18.0, gust_increase_kt=6.0),
        WindLayer(altitude_ft=5000.0, direction_deg=230.0, speed_kt=30.0, turbulence_ratio=0.3),
    ],
    cloud_layers=[
        CloudLayer(base_ft=1800.0, tops_ft=4500.0, coverage_ratio=0.75, cloud_type="stratus")
    ],
    visibility_m=5000.0,
    qnh_hpa=1002.0,
    temperature_c=22.0,
    dewpoint_c=18.0,
    precipitation_ratio=0.4,
    runway_contamination="wet",
)


def _vis_tolerance_m(adapter_name: str, value_m: float) -> float:
    """Turn the fractional ``vis_ratio`` tolerance into an absolute one."""
    return WEATHER_READBACK_TOLERANCE[adapter_name]["vis_ratio"] * value_m + 1.0


async def test_set_weather_round_trips(adapter: SimAdapter) -> None:
    """Write a full, distinctive setup; read it back within tolerance.

    The flag's coverage entry (weather-manager.md §5.3 case 1).
    """
    if not adapter.capabilities.can_set_weather:
        pytest.skip(f"{adapter.name} does not declare can_set_weather")

    tol = WEATHER_READBACK_TOLERANCE[adapter.name]
    await adapter.set_weather(_DISTINCTIVE_WEATHER)
    state = await adapter.get_weather()

    assert len(state.wind_layers) == 2
    assert state.wind_layers[0].direction_deg == pytest.approx(200.0, abs=tol["dir_deg"])
    assert state.wind_layers[0].speed_kt == pytest.approx(18.0, abs=tol["speed_kt"])
    assert len(state.cloud_layers) == 1
    assert state.cloud_layers[0].base_ft == pytest.approx(1800.0, abs=tol["base_ft"])
    assert state.cloud_layers[0].coverage_ratio == pytest.approx(0.75, abs=tol["coverage"])
    assert state.qnh_hpa == pytest.approx(1002.0, abs=tol["qnh_hpa"])
    assert state.temperature_c == pytest.approx(22.0, abs=tol["temp_c"])
    assert state.runway_contamination == "wet"


async def test_set_weather_applies_only_the_provided_fields(adapter: SimAdapter) -> None:
    """The ``None``-means-untouched half of D2."""
    if not adapter.capabilities.can_set_weather:
        pytest.skip(f"{adapter.name} does not declare can_set_weather")

    tol = WEATHER_READBACK_TOLERANCE[adapter.name]
    await adapter.set_weather(_DISTINCTIVE_WEATHER)
    await adapter.set_weather(WeatherSetup(visibility_m=2_000.0))
    state = await adapter.get_weather()

    assert state.visibility_m == pytest.approx(2_000.0, abs=_vis_tolerance_m(adapter.name, 2_000.0))
    assert state.qnh_hpa == pytest.approx(1002.0, abs=tol["qnh_hpa"])
    assert state.temperature_c == pytest.approx(22.0, abs=tol["temp_c"])


async def test_set_weather_replaces_layer_lists_wholesale(adapter: SimAdapter) -> None:
    """D3: a provided list replaces the whole set; ``[]`` clears it."""
    if not adapter.capabilities.can_set_weather:
        pytest.skip(f"{adapter.name} does not declare can_set_weather")

    two_layers = WeatherSetup(
        cloud_layers=[
            CloudLayer(base_ft=1000.0, tops_ft=3000.0, coverage_ratio=0.5),
            CloudLayer(base_ft=8000.0, tops_ft=12_000.0, coverage_ratio=1.0),
        ]
    )
    await adapter.set_weather(two_layers)
    state = await adapter.get_weather()
    assert len(state.cloud_layers) == 2

    one_layer = WeatherSetup(
        cloud_layers=[CloudLayer(base_ft=1000.0, tops_ft=3000.0, coverage_ratio=0.5)]
    )
    await adapter.set_weather(one_layer)
    state = await adapter.get_weather()
    assert len(state.cloud_layers) == 1

    await adapter.set_weather(WeatherSetup(cloud_layers=[]))
    state = await adapter.get_weather()
    assert state.cloud_layers == []


async def test_set_weather_holds_across_the_sims_update_cycle(adapter: SimAdapter) -> None:
    """Roadmap Phase 2 exit criterion 3.

    A written value must still be there after the simulator's own update
    cycle has had a chance to destroy it — the whole reason X-Plane's
    real-weather mode must be forced into manual before anything is written
    (weather-manager.md §7.1). Nearly free against the Fake; against a live
    X-Plane this run starts from whatever weather mode the user left it in.
    """
    if not adapter.capabilities.can_set_weather:
        pytest.skip(f"{adapter.name} does not declare can_set_weather")

    await adapter.set_weather(WeatherSetup(visibility_m=1234.0))
    await asyncio.sleep(WEATHER_HOLD_S[adapter.name])
    state = await adapter.get_weather()
    assert state.visibility_m == pytest.approx(1234.0, abs=_vis_tolerance_m(adapter.name, 1234.0))


async def test_get_weather_returns_a_valid_state(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_set_weather:
        pytest.skip(f"{adapter.name} does not declare can_set_weather")

    state = await adapter.get_weather()
    assert isinstance(state, WeatherState)
    altitudes = [layer.altitude_ft for layer in state.wind_layers]
    assert altitudes == sorted(altitudes)
    bases = [layer.base_ft for layer in state.cloud_layers]
    assert bases == sorted(bases)
    assert state.dewpoint_c <= state.temperature_c
    assert 0.0 <= state.precipitation_ratio <= 1.0


# --------------------------------------------------------------------------
# can_inject_failures
# --------------------------------------------------------------------------


def _active_keys(active: tuple[ActiveFailure, ...]) -> set[tuple[str, int | None]]:
    """(failure_id, engine_index) pairs — sidesteps pydantic's exact-class
    equality (an ``ActiveFailure`` never compares equal to a ``FailureRef``,
    even with identical fields)."""
    return {(item.failure_id, item.engine_index) for item in active}


async def test_failure_support_covers_the_whole_catalogue(adapter: SimAdapter) -> None:
    """Capability-free: every adapter answers, for every id, supported or not."""
    manifest = await adapter.get_failure_support()
    assert [entry.failure_id for entry in manifest.entries] == list(FAILURE_IDS)
    for entry in manifest.entries:
        if not entry.supported:
            assert entry.reason


async def test_injected_failure_is_reported_active(adapter: SimAdapter) -> None:
    """The flag's coverage entry.

    The read-back is the assertion, not the absence of an exception — the
    same lesson as issue #39: a write is not delivered until something reads
    it back at the other end.
    """
    if not adapter.capabilities.can_inject_failures:
        pytest.skip(f"{adapter.name} does not declare can_inject_failures")

    ref = FailureRef(failure_id="instruments.pitot")
    try:
        await adapter.inject_failure(ref)
        active = await adapter.get_active_failures()
        assert (ref.failure_id, ref.engine_index) in _active_keys(active)
    finally:
        await adapter.clear_failure(ref)


async def test_indexed_failure_carries_its_engine_index(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_inject_failures:
        pytest.skip(f"{adapter.name} does not declare can_inject_failures")

    ref = FailureRef(failure_id="engine.failure", engine_index=2)
    try:
        await adapter.inject_failure(ref)
        keys = _active_keys(await adapter.get_active_failures())
        assert ("engine.failure", 2) in keys
        assert ("engine.failure", 1) not in keys
    finally:
        await adapter.clear_failure(ref)


async def test_clear_failure_repairs_it(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_inject_failures:
        pytest.skip(f"{adapter.name} does not declare can_inject_failures")

    ref = FailureRef(failure_id="instruments.vacuum")
    await adapter.inject_failure(ref)
    await adapter.clear_failure(ref)
    keys = _active_keys(await adapter.get_active_failures())
    assert (ref.failure_id, ref.engine_index) not in keys


async def test_clear_all_failures_leaves_none_active(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_inject_failures:
        pytest.skip(f"{adapter.name} does not declare can_inject_failures")

    first = FailureRef(failure_id="engine.fire", engine_index=1)
    second = FailureRef(failure_id="instruments.static")
    try:
        await adapter.inject_failure(first)
        await adapter.inject_failure(second)
        await adapter.clear_all_failures()
        keys = _active_keys(await adapter.get_active_failures())
        assert (first.failure_id, first.engine_index) not in keys
        assert (second.failure_id, second.engine_index) not in keys
    finally:
        await adapter.clear_all_failures()


async def test_inject_is_idempotent(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_inject_failures:
        pytest.skip(f"{adapter.name} does not declare can_inject_failures")

    ref = FailureRef(failure_id="avionics.com1")
    try:
        await adapter.inject_failure(ref)
        await adapter.inject_failure(ref)
        active = await adapter.get_active_failures()
        # Injected twice, present once — inject is a state, not a delta.
        assert sum(1 for item in active if item.failure_id == ref.failure_id) == 1
        await adapter.clear_failure(ref)
        keys = _active_keys(await adapter.get_active_failures())
        assert (ref.failure_id, ref.engine_index) not in keys
    finally:
        await adapter.clear_failure(ref)


# --------------------------------------------------------------------------
# can_set_fuel_payload
# --------------------------------------------------------------------------

_DISTINCTIVE_LOADOUT = Loadout(
    tanks=[TankFuel(tank_index=0, fuel_kg=52.0), TankFuel(tank_index=1, fuel_kg=40.0)],
    stations=[
        PayloadStation(station_index=0, kind="crew", label="Pilot", weight_kg=85.0),
        PayloadStation(station_index=1, kind="passenger", label="Rear seats", weight_kg=60.0),
    ],
)


async def test_set_loadout_round_trips(adapter: SimAdapter) -> None:
    """The flag's coverage entry (fuel-payload.md §5.3 case 1).

    Asserts on stated masses by index, not on ``len(state.tanks/stations)``: a
    real airframe's tank/station slots are a fixed physical property of the
    loaded aircraft (X-Plane 12.4.3, measured live, exposes no dataref naming
    how many payload stations exist at all — ``m_stations`` is always read as
    the whole fixed array), so a real adapter can zero a slot but can never
    make it stop existing. ``Loadout``/``LoadoutState``'s own contract (D10,
    ``core/models.py::LoadoutState``) is "every *known* tank" — mass alone
    does not decide whether a slot is known. Every named tank/station gets its
    stated mass; that every *other* known slot is zeroed is asserted in
    :func:`test_loadout_replaces_tanks_and_stations_wholesale` below.
    """
    if not adapter.capabilities.can_set_fuel_payload:
        pytest.skip(f"{adapter.name} does not declare can_set_fuel_payload")

    tol = LOADOUT_KG_TOLERANCE[adapter.name]
    await adapter.apply_setup(AircraftSetup(loadout=_DISTINCTIVE_LOADOUT))
    state = await adapter.get_loadout()

    by_tank = {tank.tank_index: tank.fuel_kg for tank in state.tanks}
    assert by_tank[0] == pytest.approx(52.0, abs=tol)
    assert by_tank[1] == pytest.approx(40.0, abs=tol)
    by_station = {station.station_index: station.weight_kg for station in state.stations}
    assert by_station[0] == pytest.approx(85.0, abs=tol)
    assert by_station[1] == pytest.approx(60.0, abs=tol)


async def test_loadout_replaces_tanks_and_stations_wholesale(adapter: SimAdapter) -> None:
    """D10: a provided list replaces the whole set; ``[]`` empties it.

    Asserted by mass, not by ``len(state.tanks)`` shrinking: measured live
    against X-Plane 12.4.3, a wholesale-replace write can only zero a real
    airframe's *other* known tanks, never remove them from ``m_fuel`` — the
    array is fixed-size and physical (see
    ``adapters/xplane/xplane_adapter.py::_write_loadout``'s docstring for the
    live finding this resolved). "Empties it" is the honest reading for a
    real aircraft too: draining a tank to 0 kg empties it without making it
    cease to exist. ``Fake`` genuinely shrinks its own backing list (it has
    no physical array to answer to) and satisfies every assertion below
    trivially either way, so this still exercises the Fake exactly as before.
    """
    if not adapter.capabilities.can_set_fuel_payload:
        pytest.skip(f"{adapter.name} does not declare can_set_fuel_payload")

    tol = LOADOUT_KG_TOLERANCE[adapter.name]
    two_tanks = Loadout(
        tanks=[TankFuel(tank_index=0, fuel_kg=10.0), TankFuel(tank_index=1, fuel_kg=10.0)]
    )
    await adapter.apply_setup(AircraftSetup(loadout=two_tanks))
    state = await adapter.get_loadout()
    by_tank = {tank.tank_index: tank.fuel_kg for tank in state.tanks}
    assert by_tank[0] == pytest.approx(10.0, abs=tol)
    assert by_tank[1] == pytest.approx(10.0, abs=tol)

    one_tank = Loadout(tanks=[TankFuel(tank_index=0, fuel_kg=10.0)])
    await adapter.apply_setup(AircraftSetup(loadout=one_tank))
    state = await adapter.get_loadout()
    by_tank = {tank.tank_index: tank.fuel_kg for tank in state.tanks}
    assert by_tank[0] == pytest.approx(10.0, abs=tol)
    # Zeroed, not necessarily absent -- tank 1 still exists on a real airframe.
    assert by_tank.get(1, 0.0) == pytest.approx(0.0, abs=tol)

    await adapter.apply_setup(AircraftSetup(loadout=Loadout(tanks=[])))
    state = await adapter.get_loadout()
    assert all(tank.fuel_kg == pytest.approx(0.0, abs=tol) for tank in state.tanks)


async def test_get_loadout_returns_a_valid_state(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_set_fuel_payload:
        pytest.skip(f"{adapter.name} does not declare can_set_fuel_payload")

    state = await adapter.get_loadout()
    assert isinstance(state, LoadoutState)
    assert all(tank.fuel_kg >= 0.0 for tank in state.tanks)
    assert all(station.weight_kg >= 0.0 for station in state.stations)
    tank_indices = [tank.tank_index for tank in state.tanks]
    assert len(tank_indices) == len(set(tank_indices))
    station_indices = [station.station_index for station in state.stations]
    assert len(station_indices) == len(set(station_indices))


# --------------------------------------------------------------------------
# Capability-free reads
# --------------------------------------------------------------------------


async def test_get_airframe_returns_a_model(adapter: SimAdapter) -> None:
    """``get_airframe`` answers on every adapter, and "unknown" is an answer.

    A capability-free read: there is no flag to check first, because reads
    degrade instead of failing (issue #82 — the consumer is a *default*, and a
    connection refused over an unreadable stall speed would be absurd). Nothing
    here asserts a specific airframe: what is loaded in a live simulator is the
    user's business. What is pinned is the shape — a model, never an exception,
    with fields that are either absent or plausible.
    """
    airframe = await adapter.get_airframe()
    assert isinstance(airframe, AirframeInfo)
    if airframe.vso_kias is not None:
        assert airframe.vso_kias > 0.0
    if airframe.icao_type is not None:
        assert airframe.icao_type == airframe.icao_type.strip()
        assert airframe.icao_type
    if airframe.mass_limits is not None:
        assert isinstance(airframe.mass_limits, AirframeMassLimits)
        assert airframe.mass_limits.empty_weight_kg > 0.0
        assert airframe.mass_limits.max_takeoff_weight_kg > 0.0


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


async def test_stream_state_yields_several_states(adapter: SimAdapter) -> None:
    states = await _take(adapter.stream_state(STREAM_INTERVAL_S), 3)
    assert len(states) == 3
    assert all(isinstance(state, AircraftState) for state in states)


async def test_stream_state_tracks_a_moving_aircraft(adapter: SimAdapter) -> None:
    """A stream must reflect movement, not repeat a frozen snapshot.

    The ``adapter`` fixture has already put the aircraft into level flight at
    :data:`STABILISED_IAS_KT`, clear of the ground, so there is nothing to set
    up here and — deliberately — nothing to skip over. A stationary aircraft
    used to make this test skip itself; that hid a broken harness behind a green
    run. If the aircraft is not moving now, the stabilisation is broken, and
    that is the finding.
    """
    states = await _take(adapter.stream_state(STREAM_INTERVAL_S), 4)
    assert states[0].ias_kt > 0.0, (
        "the aircraft has no airspeed: the stabilisation in the `adapter` fixture "
        "did not take effect, so movement cannot be observed"
    )
    positions = {(state.latitude, state.longitude) for state in states}
    assert len(positions) > 1, "stream_state repeated the same position on every tick"


async def test_stream_state_can_be_restarted(adapter: SimAdapter) -> None:
    assert len(await _take(adapter.stream_state(STREAM_INTERVAL_S), 2)) == 2
    assert len(await _take(adapter.stream_state(STREAM_INTERVAL_S), 2)) == 2


# --------------------------------------------------------------------------
# Fake-only: fields that do not surface in AircraftState
# --------------------------------------------------------------------------


async def test_fake_apply_setup_records_non_state_fields() -> None:
    """Lights, gear and radios have no ``AircraftState`` mirror to check.

    The reference implementation exposes ``applied_setup`` so the merge
    semantics ("apply what is given, keep the rest") are pinned somewhere. Real
    adapters are validated against the simulator under ``-m sim``.
    """
    sim = FakeSimAdapter()
    await sim.connect()
    try:
        await sim.apply_setup(
            AircraftSetup(
                gear_down=True,
                flaps_ratio=0.5,
                nav1_freq_khz=110_300,
                lights=LightsSetup(landing=True, strobe=True),
            )
        )
        await sim.apply_setup(AircraftSetup(flaps_ratio=1.0, lights=LightsSetup(taxi=True)))

        applied = sim.applied_setup
        assert applied.gear_down is True  # untouched by the second call
        assert applied.flaps_ratio == 1.0  # overwritten by the second call
        assert applied.nav1_freq_khz == 110_300
        assert applied.lights is not None
        assert applied.lights.landing is True  # merged, not replaced
        assert applied.lights.strobe is True
        assert applied.lights.taxi is True
        assert applied.speedbrake_ratio is None  # never provided, still unset
    finally:
        await sim.disconnect()


async def test_fake_reports_the_configured_airframe() -> None:
    """The Fake's constructor-settable airframe round-trips through the read.

    This is the affordance A2 (issue #82) builds its server tests on: a Fake
    carrying a known Vso lets the category-derivation chain be pinned in CI
    without a simulator.
    """
    sim = FakeSimAdapter(airframe=AirframeInfo(icao_type="C172", vso_kias=48.0))
    await sim.connect()
    try:
        airframe = await sim.get_airframe()
        assert airframe.icao_type == "C172"
        assert airframe.vso_kias == pytest.approx(48.0)

        unknown = await FakeSimAdapter().get_airframe()
        assert unknown == AirframeInfo()
    finally:
        await sim.disconnect()


async def test_fake_merges_the_autopilot_across_calls() -> None:
    """The autopilot block merges like every other field — no special casing.

    ``FakeSimAdapter._merge_setup`` is driven by ``model_dump(exclude_none=True)``,
    so the ten fields issue #41 added were carried with no change to the adapter.
    This is the test that keeps that true: a future field that needs bespoke merge
    logic (as ``lights`` does) has to be noticed here rather than in a simulator.
    """
    sim = FakeSimAdapter()
    await sim.connect()
    try:
        await sim.apply_setup(
            AircraftSetup(
                autopilot_master=True, target_altitude_ft=8000.0, elevator_trim_ratio=-0.2
            )
        )
        await sim.apply_setup(AircraftSetup(target_altitude_ft=12_000.0, autopilot_app=True))

        applied = sim.applied_setup
        assert applied.autopilot_master is True  # untouched by the second call
        assert applied.elevator_trim_ratio == pytest.approx(-0.2)
        assert applied.target_altitude_ft == pytest.approx(12_000.0)  # overwritten
        assert applied.autopilot_app is True
        assert applied.autopilot_nav is None  # never provided, still unset
    finally:
        await sim.disconnect()


async def test_get_airframe_reports_mass_limits_when_known() -> None:
    """A Fake constructed with ``AirframeInfo(mass_limits=...)`` returns it
    verbatim; the default Fake returns ``None`` (fuel-payload.md §5.3 case 4).

    No live adapter can be handed a specific answer this way (the parametrised
    ``adapter`` fixture builds a plain, default instance) — that half is
    covered by the shape assertion in :func:`test_get_airframe_returns_a_model`.
    """
    limits = AirframeMassLimits(
        empty_weight_kg=743.0,
        empty_cg_arm_in=39.0,
        max_takeoff_weight_kg=1157.0,
        max_fuel_kg=152.0,
        fuel_tank_capacities_kg=(76.0, 76.0),
        fuel_tank_arms_in=(48.0, 48.0),
        payload_station_capacities_kg=(85.0, 85.0, 45.0),
        payload_station_arms_in=(37.0, 73.0, 95.0),
        cg_envelope=CgEnvelope(
            points=(
                CgEnvelopePoint(weight_kg=700.0, fwd_limit_in=34.0, aft_limit_in=41.0),
                CgEnvelopePoint(weight_kg=1157.0, fwd_limit_in=35.5, aft_limit_in=40.0),
            )
        ),
    )
    sim = FakeSimAdapter(airframe=AirframeInfo(icao_type="C172", mass_limits=limits))
    await sim.connect()
    try:
        airframe = await sim.get_airframe()
        assert airframe.mass_limits == limits

        unknown = await FakeSimAdapter().get_airframe()
        assert unknown.mass_limits is None
    finally:
        await sim.disconnect()


# --------------------------------------------------------------------------
# Fake-only: capability refusal for the Phase 2 methods
# --------------------------------------------------------------------------
#
# The parametrised ``adapter`` fixture cannot exercise these: FakeSimAdapter
# declares every capability (test_fake_adapter_declares_every_capability), so
# a skip-guarded case against it would never actually run — exactly the
# "green run that hid something" this file's own docstring warns against. A
# restricted subclass, overriding only ``capabilities``, is the shape the
# existing _NoWriteAdapter/NoPositionAdapter precedent already established
# for this in ``tests/server/test_app.py``/``tests/server/test_position_routes.py``.


async def test_weather_methods_refuse_without_the_capability() -> None:
    class NoWeatherAdapter(FakeSimAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_set_weather": False})

    sim = NoWeatherAdapter()
    await sim.connect()
    try:
        with pytest.raises(CapabilityNotSupported, match="can_set_weather"):
            await sim.get_weather()
        with pytest.raises(CapabilityNotSupported, match="can_set_weather"):
            await sim.set_weather(WeatherSetup(visibility_m=1000.0))
    finally:
        await sim.disconnect()


async def test_failure_methods_refuse_without_the_capability() -> None:
    class NoFailuresAdapter(FakeSimAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_inject_failures": False})

    sim = NoFailuresAdapter()
    await sim.connect()
    try:
        ref = FailureRef(failure_id="instruments.pitot")
        with pytest.raises(CapabilityNotSupported, match="can_inject_failures"):
            await sim.inject_failure(ref)
        with pytest.raises(CapabilityNotSupported, match="can_inject_failures"):
            await sim.clear_failure(ref)
        with pytest.raises(CapabilityNotSupported, match="can_inject_failures"):
            await sim.clear_all_failures()

        manifest = await sim.get_failure_support()
        assert all(not entry.supported for entry in manifest.entries)
        assert all(entry.reason for entry in manifest.entries)
        assert await sim.get_active_failures() == ()
    finally:
        await sim.disconnect()


async def test_loadout_methods_refuse_without_the_capability() -> None:
    class NoFuelPayloadAdapter(FakeSimAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_set_fuel_payload": False})

    sim = NoFuelPayloadAdapter()
    await sim.connect()
    try:
        with pytest.raises(CapabilityNotSupported, match="can_set_fuel_payload"):
            await sim.get_loadout()
        with pytest.raises(CapabilityNotSupported, match="can_set_fuel_payload"):
            await sim.apply_setup(
                AircraftSetup(loadout=Loadout(tanks=[TankFuel(tank_index=0, fuel_kg=1.0)]))
            )
    finally:
        await sim.disconnect()
