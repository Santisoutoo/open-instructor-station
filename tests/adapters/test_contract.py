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

from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError

from adapters.fake import FakeSimAdapter
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.models import AircraftSetup, AircraftState, GeoPosition, LightsSetup
from core.sim_adapter import Capabilities, SimAdapter

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
#: the distance is not part of it. Long-haul repositioning across a scenery
#: reload is an *adapter* concern, tracked separately; see
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

#: How far a grounded aircraft is lifted before the tests run. Vertical only —
#: the horizontal position is untouched, so this never triggers a scenery
#: reload.
GROUND_CLEARANCE_FT = 1500.0

#: Which test pins each capability. ``PENDING`` marks a flag whose manager
#: arrives in a later phase: the contract is not written yet, and that is a
#: deliberate, visible decision rather than an oversight.
PENDING = "PENDING - contract arrives with the manager that implements it"

CAPABILITY_COVERAGE: dict[str, str] = {
    "can_set_position": "test_set_position_moves_the_aircraft",
    "can_set_aircraft_state": "test_apply_setup_applies_only_the_provided_fields",
    "can_set_weather": PENDING,
    "can_inject_failures": PENDING,
    "can_spawn_traffic": PENDING,
    "can_control_autopilot": PENDING,
    "can_set_fuel_payload": PENDING,
    "can_control_camera": PENDING,
    "can_pushback": PENDING,
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
    target is the wrong shape for this assertion.
    """
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    target = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 0.0)
    try:
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


async def test_set_position_normalises_the_heading(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_set_position:
        pytest.skip(f"{adapter.name} does not declare can_set_position")

    original = await adapter.get_aircraft_state()
    home = _position_of(original)
    target = point_at_distance_and_bearing(home, HOP_DISTANCE_NM, 180.0)
    try:
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
    """
    if not adapter.capabilities.can_set_aircraft_state:
        pytest.skip(f"{adapter.name} does not declare can_set_aircraft_state")

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
    if not adapter.capabilities.can_set_aircraft_state:
        pytest.skip(f"{adapter.name} does not declare can_set_aircraft_state")
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
