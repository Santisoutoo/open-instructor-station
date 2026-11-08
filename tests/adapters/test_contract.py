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
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from adapters.fake import FakeSimAdapter
from core.camera.models import (
    CAMERA_VIEW_IDS,
    CameraOffset,
    CameraSupportManifest,
    CameraViewId,
)
from core.cockpit.actuation import is_on, selector_index
from core.cockpit.errors import (
    CockpitCatalogInactive,
    CockpitControlUnknown,
    CockpitPreconditionUnmet,
)
from core.cockpit.models import (
    CockpitActuation,
    CockpitAircraft,
    CockpitBinding,
    CockpitCatalogDocument,
    CockpitControlDefinition,
    CockpitControlKind,
    CockpitControlSpec,
    CockpitDetection,
    CockpitPanel,
    CockpitValue,
)
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
from core.pushback import PushbackNotOnGround, PushbackRequest
from core.sim_adapter import Capabilities, CapabilityNotSupported, SimAdapter
from core.traffic import (
    TrafficCapacityExceeded,
    TrafficContact,
    TrafficTrack,
    TrafficWaypoint,
)
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

#: How far a freshly spawned traffic entity may already sit from its track's
#: first waypoint when it is read back, in nautical miles. Never zero even for
#: the Fake: an entity starts moving along its track the instant it spawns, so
#: the read-back happens a real (if tiny) elapsed time later. A live bridge
#: adds command/ack latency on top (docs/designs/ai-traffic.md §5.1).
TRAFFIC_SPAWN_TOLERANCE_NM = {"fake": 0.01, "xplane": 0.25}

#: Geometry of the track :func:`test_traffic_advances_along_its_track` spawns:
#: the second waypoint sits :data:`TRAFFIC_ADVANCE_LEG_NM` away, reached at
#: ``t_offset_s`` = :data:`TRAFFIC_ADVANCE_LEG_TIME_S` — 0.15 NM in 2 s is
#: 270 kt, a realistic jet ground speed, and a displacement (~280 m) far
#: outside any read-back tolerance, so "it moved" cannot be confused with
#: noise.
TRAFFIC_ADVANCE_LEG_NM = 0.15
TRAFFIC_ADVANCE_LEG_TIME_S = 2.0

#: Movement that counts as "the entity is really advancing", in nautical
#: miles from the spawn waypoint (~90 m — a third of the leg, reached well
#: inside the poll window on any correct implementation).
TRAFFIC_MOVED_MIN_NM = 0.05

#: How long the advance test polls before declaring the entity stuck. Longer
#: than the whole leg, so even an implementation that only updates positions
#: lazily on read has had every chance.
TRAFFIC_ADVANCE_TIMEOUT_S = 6.0

#: Hard ceiling on the capacity-enforcement spawn loop. No adapter is expected
#: to allow anywhere near this many concurrent entities; hitting the bound
#: without a refusal means capacity is simply not enforced.
TRAFFIC_CAPACITY_PROBE_LIMIT = 100

#: Track timing for :func:`test_traffic_expires_after_despawn_after_s`: the
#: track's last waypoint is reached at :data:`TRAFFIC_EXPIRY_LEG_TIME_S` and
#: automatic despawn is due :data:`TRAFFIC_EXPIRY_DESPAWN_AFTER_S` later — a
#: 2 s nominal lifetime, short enough to keep the suite fast, long enough that
#: the read taken immediately after spawn cannot race the expiry.
TRAFFIC_EXPIRY_LEG_TIME_S = 1.0
TRAFFIC_EXPIRY_DESPAWN_AFTER_S = 1.0

#: How long past the nominal expiry the test keeps polling before declaring
#: the entity immortal. Generous: lazy expiry only has to happen on *a* read
#: after the deadline, not at the deadline.
TRAFFIC_EXPIRY_GRACE_S = 4.0

#: Slack on the "never disappears early" lower bound, absorbing the clock
#: reads on either side of the spawn call itself.
TRAFFIC_EXPIRY_CLOCK_EPSILON_S = 0.05

#: How far a pushed-back aircraft may end up from the manoeuvre's computed
#: chord, in metres (pushback-manager.md §4.2). Tighter than
#: :data:`POSITION_TOLERANCE_M`: the manoeuvre itself is short and there is no
#: re-acceleration afterward to absorb drift.
PUSHBACK_TOLERANCE_M = {"fake": 0.1, "xplane": 5.0}

#: How far a camera offset read back may sit from the one written, in
#: metres for the translation fields and degrees for the angular ones
#: (camera-manager.md §4.2). Mirrors :data:`LOADOUT_KG_TOLERANCE`'s
#: reasoning: the Fake stores exactly what it is handed, while a live
#: simulator round-trips a pose through single-precision datarefs.
CAMERA_OFFSET_TOLERANCE = {"fake": 0.001, "xplane": 0.5}

#: Where the camera tests leave the camera. ``"cockpit"`` is the least
#: surprising resting place for an instructor who walks back to the
#: simulator, and the suite's third live rule (*restore anything you move*)
#: has nothing better to aim at here: ``SimAdapter`` deliberately exposes no
#: *read* of the current named view, only :meth:`get_camera_offset`. A camera
#: move changes no aircraft state at all, so this is courtesy rather than
#: safety; the true original-view restore belongs to
#: ``tests/sim/test_live_camera.py`` (camera-manager.md §8.3), which can
#: capture the view before it starts.
CAMERA_RESTING_VIEW: CameraViewId = "cockpit"

#: Per-adapter dial/encoder read-back tolerance for the cockpit contract
#: tests (docs/designs/cockpit-control-catalog.md §4.2). ``None`` means "use
#: the entry's own ``readback_tolerance``" — a live catalog states its own
#: tolerance per control (§3.1), so there is no single fixed number that
#: would work across every X-Plane dial the way :data:`COMMANDED_IAS_TOLERANCE_KT`
#: does for a single flight-state field.
COCKPIT_READBACK_TOLERANCE: dict[str, float | None] = {"fake": 0.0, "xplane": None}

#: Which test pins each capability. ``PENDING`` marks a flag whose manager
#: arrives in a later phase: the contract is not written yet, and that is a
#: deliberate, visible decision rather than an oversight.
PENDING = "PENDING - contract arrives with the manager that implements it"

CAPABILITY_COVERAGE: dict[str, str] = {
    "can_set_position": "test_set_position_moves_the_aircraft",
    "can_set_aircraft_state": "test_apply_setup_applies_only_the_provided_fields",
    "can_set_weather": "test_set_weather_round_trips",
    "can_inject_failures": "test_injected_failure_is_reported_active",
    "can_spawn_traffic": "test_spawned_traffic_is_reported_active",
    "can_control_autopilot": "test_apply_setup_writes_the_autopilot",
    "can_set_fuel_payload": "test_set_loadout_round_trips",
    "can_control_camera": "test_set_camera_view_is_accepted_for_every_supported_view",
    "can_pushback": "test_pushback_moves_the_aircraft_backward",
    "can_control_cockpit": "test_actuate_toggle_round_trips",
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


#: A parked, on-ground aircraft, constructed directly rather than reached
#: through the interface — ``on_ground`` has no write path on ``SimAdapter``
#: (it is derived from the simulator's own physics, never a settable field),
#: so ``grounded_adapter`` below cannot ask a freshly-``_stabilise``d Fake to
#: land the way it asks a live one to.
GROUNDED_FAKE_STATE = AircraftState(
    latitude=40.4936,
    longitude=-3.5668,
    altitude_ft=2000.0,
    heading_deg=90.0,
    ias_kt=0.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=True,
)


@pytest.fixture(params=ADAPTER_PARAMS)
async def grounded_adapter(request: pytest.FixtureRequest) -> AsyncIterator[SimAdapter]:
    """A connected adapter whose aircraft is on the ground, for pushback tests.

    Pushback is only meaningful from a parked aircraft, and unlike every other
    capability this suite exercises, ``on_ground`` cannot be written through
    ``SimAdapter`` at all — it is read-only and derived from the simulator's
    own physics. The Fake is therefore constructed directly with an on-ground
    state (:data:`GROUNDED_FAKE_STATE`) instead of going through the
    ``_stabilise``-into-flight path the shared ``adapter`` fixture uses.

    A live simulator's ground state is whatever the user loaded. This asks it
    to settle by teleporting to its own current position at ``ias_kt=0`` — the
    same live-only wrinkle ``docs/designs/pushback-manager.md`` §8.3 documents
    for the sim-only pushback tests — and skips with a clear reason if it still
    does not report ``on_ground`` afterward, rather than retrying forever. This
    branch never runs in CI: the ``xplane`` parametrisation only executes under
    ``pytest -m sim``.
    """
    if request.param == "fake":
        fake_instance = FakeSimAdapter(initial_state=GROUNDED_FAKE_STATE)
        await fake_instance.connect()
        try:
            yield fake_instance
        finally:
            await fake_instance.disconnect()
        return

    instance = _build(request.param)
    await instance.connect()
    try:
        state = await instance.get_aircraft_state()
        if not state.on_ground and instance.capabilities.can_set_position:
            here = _position_of(state)
            await instance.set_position(here, heading_deg=state.heading_deg, ias_kt=0.0)
            state = await instance.get_aircraft_state()
        if not state.on_ground:
            pytest.skip(
                f"{instance.name}: the aircraft did not settle on the ground for the "
                "pushback fixture — a live-sim environmental precondition, not a "
                "contract failure."
            )
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
# can_spawn_traffic
# --------------------------------------------------------------------------


def _traffic_track(
    anchor: GeoPosition,
    *,
    callsign: str = "TFC01",
    bearing_deg: float = 0.0,
    leg_nm: float = TRAFFIC_ADVANCE_LEG_NM,
    leg_time_s: float = TRAFFIC_ADVANCE_LEG_TIME_S,
    despawn_after_s: float | None = None,
) -> TrafficTrack:
    """A minimal two-waypoint ``custom`` track near ``anchor``.

    Anchored to the aircraft's own position (live-suite rule 2): against a real
    simulator an absolute coordinate could spawn an entity a continent away
    from the loaded scenery. The track sits 2 NM off to the requested bearing
    and 1000 ft above the anchor, so it never touches the user's aircraft.
    """
    start = point_at_distance_and_bearing(anchor, 2.0, bearing_deg)
    start = GeoPosition(
        latitude=start.latitude,
        longitude=start.longitude,
        altitude_ft=anchor.altitude_ft + 1000.0,
    )
    end_horizontal = point_at_distance_and_bearing(start, leg_nm, bearing_deg)
    end = GeoPosition(
        latitude=end_horizontal.latitude,
        longitude=end_horizontal.longitude,
        altitude_ft=start.altitude_ft,
    )
    speed_kt = leg_nm / leg_time_s * 3600.0
    return TrafficTrack(
        kind="aircraft",
        scenario_shape="custom",
        callsign=callsign,
        label="contract-suite traffic",
        waypoints=(
            TrafficWaypoint(position=start, speed_kt=speed_kt, t_offset_s=0.0),
            TrafficWaypoint(position=end, speed_kt=speed_kt, t_offset_s=leg_time_s),
        ),
        despawn_after_s=despawn_after_s,
    )


def _contact_position(contact: TrafficContact) -> GeoPosition:
    return GeoPosition(latitude=contact.latitude, longitude=contact.longitude)


def _by_id(contacts: tuple[TrafficContact, ...], traffic_id: str) -> TrafficContact | None:
    return next((c for c in contacts if c.traffic_id == traffic_id), None)


async def test_spawned_traffic_is_reported_active(adapter: SimAdapter) -> None:
    """The flag's coverage entry: spawn, then read the entity back.

    The read-back is the assertion, not the absence of an exception — the
    issue #39 lesson, restated once more: a track handed to ``spawn_traffic``
    is not delivered until ``get_traffic_contacts`` reports an entity at the
    track's first waypoint.
    """
    if not adapter.capabilities.can_spawn_traffic:
        pytest.skip(f"{adapter.name} does not declare can_spawn_traffic")

    state = await adapter.get_aircraft_state()
    track = _traffic_track(_position_of(state))
    contact = await adapter.spawn_traffic(track)
    try:
        assert isinstance(contact, TrafficContact)
        assert contact.traffic_id
        assert contact.callsign == track.callsign

        reported = _by_id(await adapter.get_traffic_contacts(), contact.traffic_id)
        assert reported is not None, "spawned traffic is missing from get_traffic_contacts()"
        error_nm, _ = distance_and_bearing(track.waypoints[0].position, _contact_position(reported))
        assert error_nm <= TRAFFIC_SPAWN_TOLERANCE_NM[adapter.name]
    finally:
        await adapter.despawn_traffic(contact.traffic_id)


async def test_despawn_is_idempotent(adapter: SimAdapter) -> None:
    """An unknown or already-gone id is a no-op, never an error."""
    if not adapter.capabilities.can_spawn_traffic:
        pytest.skip(f"{adapter.name} does not declare can_spawn_traffic")

    state = await adapter.get_aircraft_state()
    contact = await adapter.spawn_traffic(_traffic_track(_position_of(state)))
    try:
        await adapter.despawn_traffic(contact.traffic_id)
        await adapter.despawn_traffic(contact.traffic_id)  # second time: still a no-op
        assert _by_id(await adapter.get_traffic_contacts(), contact.traffic_id) is None
    finally:
        await adapter.despawn_traffic(contact.traffic_id)


async def test_clear_all_traffic_leaves_none(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_spawn_traffic:
        pytest.skip(f"{adapter.name} does not declare can_spawn_traffic")

    state = await adapter.get_aircraft_state()
    anchor = _position_of(state)
    try:
        await adapter.spawn_traffic(_traffic_track(anchor, callsign="TFC01", bearing_deg=0.0))
        await adapter.spawn_traffic(_traffic_track(anchor, callsign="TFC02", bearing_deg=90.0))
        await adapter.clear_all_traffic()
        assert await adapter.get_traffic_contacts() == ()
    finally:
        await adapter.clear_all_traffic()


async def test_traffic_advances_along_its_track(adapter: SimAdapter) -> None:
    """A spawned entity really moves along its track, on the track's own clock.

    The second waypoint is materially displaced
    (:data:`TRAFFIC_ADVANCE_LEG_NM`) and reached at ``t_offset_s`` =
    :data:`TRAFFIC_ADVANCE_LEG_TIME_S`; the contact list is polled briefly (the
    failures watcher-integration pattern) until the reported position has moved
    measurably from the first waypoint toward the second — an adapter that
    echoes the spawn point back forever fails at the deadline.
    """
    if not adapter.capabilities.can_spawn_traffic:
        pytest.skip(f"{adapter.name} does not declare can_spawn_traffic")

    state = await adapter.get_aircraft_state()
    track = _traffic_track(_position_of(state))
    start = track.waypoints[0].position
    end = track.waypoints[1].position
    contact = await adapter.spawn_traffic(track)
    try:
        deadline = asyncio.get_running_loop().time() + TRAFFIC_ADVANCE_TIMEOUT_S
        moved_nm = 0.0
        remaining_nm = TRAFFIC_ADVANCE_LEG_NM
        while asyncio.get_running_loop().time() < deadline:
            reported = _by_id(await adapter.get_traffic_contacts(), contact.traffic_id)
            assert reported is not None, "the entity vanished while advancing along its track"
            here = _contact_position(reported)
            moved_nm, _ = distance_and_bearing(start, here)
            remaining_nm, _ = distance_and_bearing(here, end)
            if moved_nm >= TRAFFIC_MOVED_MIN_NM:
                break
            await asyncio.sleep(STREAM_INTERVAL_S)
        assert moved_nm >= TRAFFIC_MOVED_MIN_NM, (
            f"traffic never moved: still {moved_nm:.4f} NM from its spawn waypoint after "
            f"{TRAFFIC_ADVANCE_TIMEOUT_S} s (needed {TRAFFIC_MOVED_MIN_NM} NM)"
        )
        # Moved *toward* the second waypoint, not off in some other direction.
        assert remaining_nm <= TRAFFIC_ADVANCE_LEG_NM - TRAFFIC_MOVED_MIN_NM / 2.0
    finally:
        await adapter.despawn_traffic(contact.traffic_id)


async def test_traffic_expires_after_despawn_after_s(adapter: SimAdapter) -> None:
    """``despawn_after_s`` is honoured: the entity outlives its track by exactly
    that long, then disappears from ``get_traffic_contacts()`` on its own.

    Both halves of the timing are pinned (ai-traffic.md §3.2, §4.4):

    * **never early** — the entity must not vanish before
      ``waypoints[-1].t_offset_s + despawn_after_s``; every poll that still
      finds it before that deadline is consistent, and the moment it is first
      observed missing must sit at or after the deadline. An adapter that
      despawns at track end, ignoring the extra ``despawn_after_s``, fails
      this lower bound loudly.
    * **eventually gone** — within :data:`TRAFFIC_EXPIRY_GRACE_S` past the
      deadline the contact list no longer carries it, with no despawn call
      made. Expiry may be lazy (evaluated on read, no background task — the
      Fake's documented shape), so only *a* read after the deadline has to
      show it gone, not the first tick past it.
    """
    if not adapter.capabilities.can_spawn_traffic:
        pytest.skip(f"{adapter.name} does not declare can_spawn_traffic")

    state = await adapter.get_aircraft_state()
    track = _traffic_track(
        _position_of(state),
        leg_time_s=TRAFFIC_EXPIRY_LEG_TIME_S,
        despawn_after_s=TRAFFIC_EXPIRY_DESPAWN_AFTER_S,
    )
    lifetime_s = TRAFFIC_EXPIRY_LEG_TIME_S + TRAFFIC_EXPIRY_DESPAWN_AFTER_S
    loop = asyncio.get_running_loop()
    try:
        spawned_at = loop.time()
        contact = await adapter.spawn_traffic(track)
        # Alive immediately after spawn — expiry is measured from here.
        assert _by_id(await adapter.get_traffic_contacts(), contact.traffic_id) is not None

        deadline = spawned_at + lifetime_s + TRAFFIC_EXPIRY_GRACE_S
        first_missing_at: float | None = None
        while loop.time() < deadline:
            if _by_id(await adapter.get_traffic_contacts(), contact.traffic_id) is None:
                first_missing_at = loop.time()
                break
            await asyncio.sleep(STREAM_INTERVAL_S)

        assert first_missing_at is not None, (
            f"traffic never expired: still reported "
            f"{lifetime_s + TRAFFIC_EXPIRY_GRACE_S:.1f} s after spawn, with "
            f"despawn_after_s={TRAFFIC_EXPIRY_DESPAWN_AFTER_S} due at {lifetime_s:.1f} s"
        )
        survived_s = first_missing_at - spawned_at
        assert survived_s >= lifetime_s - TRAFFIC_EXPIRY_CLOCK_EPSILON_S, (
            f"traffic expired early: gone {survived_s:.2f} s after spawn, but "
            f"despawn_after_s only falls due at {lifetime_s:.1f} s — the entity must "
            "hold at its last waypoint until then"
        )
    finally:
        await adapter.clear_all_traffic()


async def test_spawn_capacity_is_enforced(adapter: SimAdapter) -> None:
    """One spawn past the adapter's own limit raises ``TrafficCapacityExceeded``.

    The capacity is adapter-owned (ai-traffic.md D6), so the test does not
    assume a number: it spawns until refused and pins the refusal's own
    bookkeeping. Against ``xplane`` this runs only under ``-m sim`` (the
    fixture's own parametrisation) — 19 real AI aircraft is heavy; against
    ``fake`` it runs unconditionally in CI.
    """
    if not adapter.capabilities.can_spawn_traffic:
        pytest.skip(f"{adapter.name} does not declare can_spawn_traffic")

    state = await adapter.get_aircraft_state()
    anchor = _position_of(state)
    spawned = 0
    try:
        with pytest.raises(TrafficCapacityExceeded) as excinfo:
            for index in range(TRAFFIC_CAPACITY_PROBE_LIMIT):
                await adapter.spawn_traffic(
                    _traffic_track(
                        anchor,
                        callsign=f"CAP{index:03d}",
                        bearing_deg=(index * 17.0) % 360.0,
                    )
                )
                spawned += 1
        refusal = excinfo.value
        assert refusal.capacity > 0
        assert refusal.active_count >= refusal.capacity
        assert spawned <= refusal.active_count
        # The refusal corrupted nothing: everything spawned before it is intact.
        assert len(await adapter.get_traffic_contacts()) >= spawned
    finally:
        await adapter.clear_all_traffic()


async def test_stream_traffic_reflects_spawns(adapter: SimAdapter) -> None:
    """An already-running stream picks up an entity spawned mid-stream.

    The ``stream_state`` liveness pattern applied to the traffic feed: the
    stream is started, one entity is spawned, and a subsequent tick must
    include it — a stream replaying a snapshot taken at start-up fails here.
    """
    if not adapter.capabilities.can_spawn_traffic:
        pytest.skip(f"{adapter.name} does not declare can_spawn_traffic")

    state = await adapter.get_aircraft_state()
    track = _traffic_track(_position_of(state))
    stream = adapter.stream_traffic(STREAM_INTERVAL_S)
    contact = None
    try:
        await anext(stream)  # the stream is alive before the spawn
        contact = await adapter.spawn_traffic(track)
        seen = False
        for _ in range(50):
            frame = await anext(stream)
            if _by_id(frame, contact.traffic_id) is not None:
                seen = True
                break
        assert seen, "a spawn during an open stream never appeared in any subsequent tick"
    finally:
        if contact is not None:
            await adapter.despawn_traffic(contact.traffic_id)
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()


# --------------------------------------------------------------------------
# can_pushback
# --------------------------------------------------------------------------


async def test_pushback_moves_the_aircraft_backward(grounded_adapter: SimAdapter) -> None:
    """The flag's coverage entry (pushback-manager.md §4.2).

    A straight push, ``distance_m=20``: the aircraft ends up 20 m from where it
    started, at the back bearing (the reciprocal of its heading), with the
    heading itself unchanged.
    """
    if not grounded_adapter.capabilities.can_pushback:
        pytest.skip(f"{grounded_adapter.name} does not declare can_pushback")

    before = await grounded_adapter.get_aircraft_state()
    home = _position_of(before)
    expected_back_bearing_deg = (before.heading_deg + 180.0) % 360.0
    tol_m = PUSHBACK_TOLERANCE_M[grounded_adapter.name]
    request = PushbackRequest(direction="straight", distance_m=20.0)
    try:
        await grounded_adapter.pushback(request)
        after = await grounded_adapter.get_aircraft_state()

        distance_nm, bearing_deg = distance_and_bearing(home, _position_of(after))
        assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(20.0, abs=tol_m)
        assert bearing_deg == pytest.approx(expected_back_bearing_deg, abs=2.0)
        assert after.heading_deg == pytest.approx(before.heading_deg, abs=1.0)
    finally:
        await grounded_adapter.set_position(home, heading_deg=before.heading_deg, ias_kt=0.0)


async def test_pushback_arc_rotates_heading_by_the_full_angle(grounded_adapter: SimAdapter) -> None:
    """D5's hand-checkable half, both directions: the final heading is rotated
    by exactly ``angle_deg``, clockwise for ``"right"``, counter-clockwise for
    ``"left"``.
    """
    if not grounded_adapter.capabilities.can_pushback:
        pytest.skip(f"{grounded_adapter.name} does not declare can_pushback")

    before = await grounded_adapter.get_aircraft_state()
    home = _position_of(before)

    try:
        await grounded_adapter.pushback(
            PushbackRequest(direction="right", distance_m=20.0, angle_deg=45.0)
        )
        after_right = await grounded_adapter.get_aircraft_state()
        assert after_right.heading_deg == pytest.approx(
            (before.heading_deg + 45.0) % 360.0, abs=1.0
        )
    finally:
        await grounded_adapter.set_position(home, heading_deg=before.heading_deg, ias_kt=0.0)

    try:
        await grounded_adapter.pushback(
            PushbackRequest(direction="left", distance_m=20.0, angle_deg=45.0)
        )
        after_left = await grounded_adapter.get_aircraft_state()
        assert after_left.heading_deg == pytest.approx((before.heading_deg - 45.0) % 360.0, abs=1.0)
    finally:
        await grounded_adapter.set_position(home, heading_deg=before.heading_deg, ias_kt=0.0)


async def test_pushback_refuses_when_airborne(adapter: SimAdapter) -> None:
    """D8: a precondition, not a capability — an airborne aircraft is left
    unmoved and :class:`~core.pushback.PushbackNotOnGround` is raised, even on
    an adapter that declares ``can_pushback``.

    Uses the shared, airborne ``adapter`` fixture rather than
    ``grounded_adapter`` — this is the one pushback test that specifically
    needs the aircraft *not* to be on the ground.
    """
    if not adapter.capabilities.can_pushback:
        pytest.skip(f"{adapter.name} does not declare can_pushback")

    before = await adapter.get_aircraft_state()
    assert not before.on_ground, (
        "the `adapter` fixture is expected to leave the aircraft airborne — "
        "if this fails, the fixture (not this test) is the thing to fix"
    )
    request = PushbackRequest(direction="straight", distance_m=20.0)
    with pytest.raises(PushbackNotOnGround):
        await adapter.pushback(request)

    after = await adapter.get_aircraft_state()
    assert after.latitude == pytest.approx(before.latitude)
    assert after.longitude == pytest.approx(before.longitude)
    assert after.heading_deg == pytest.approx(before.heading_deg, abs=0.5)


async def test_pushback_is_idempotent_in_direction_only(grounded_adapter: SimAdapter) -> None:
    """Two identical calls move the aircraft twice, not once.

    Pushback is a relative command, like a throttle nudge — not idempotent as
    a *state* — but each call is deterministic given its own starting state,
    so two identical straight pushes cover twice the distance of one.
    """
    if not grounded_adapter.capabilities.can_pushback:
        pytest.skip(f"{grounded_adapter.name} does not declare can_pushback")

    before = await grounded_adapter.get_aircraft_state()
    home = _position_of(before)
    tol_m = PUSHBACK_TOLERANCE_M[grounded_adapter.name]
    request = PushbackRequest(direction="straight", distance_m=20.0)
    try:
        await grounded_adapter.pushback(request)
        once = await grounded_adapter.get_aircraft_state()
        await grounded_adapter.pushback(request)
        twice = await grounded_adapter.get_aircraft_state()

        once_distance_nm, _ = distance_and_bearing(home, _position_of(once))
        twice_distance_nm, _ = distance_and_bearing(home, _position_of(twice))
        assert twice_distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(
            2.0 * once_distance_nm * METRES_PER_NAUTICAL_MILE, abs=2.0 * tol_m
        )
        assert twice.heading_deg == pytest.approx(once.heading_deg, abs=1.0)
    finally:
        await grounded_adapter.set_position(home, heading_deg=before.heading_deg, ias_kt=0.0)


# --------------------------------------------------------------------------
# can_control_camera
# --------------------------------------------------------------------------


async def _supported_view_ids(adapter: SimAdapter) -> tuple[CameraViewId, ...]:
    """The view ids ``adapter``'s own manifest reports as supported.

    Every camera test asks the adapter what it can do rather than assuming the
    catalogue: per-view support genuinely varies (camera-manager.md D2/§5.1 —
    ``wing`` has no confirmed X-Plane command at all), so "which views exist"
    and "which views work here" are different questions.
    """
    manifest = await adapter.get_camera_support()
    return tuple(entry.view_id for entry in manifest.views if entry.supported)


async def _restore_camera(adapter: SimAdapter) -> None:
    """Put the camera back at :data:`CAMERA_RESTING_VIEW`, if that view works here."""
    if CAMERA_RESTING_VIEW in await _supported_view_ids(adapter):
        await adapter.set_camera_view(CAMERA_RESTING_VIEW)


async def test_camera_support_covers_the_whole_catalogue(adapter: SimAdapter) -> None:
    """The manifest answers for every view, in catalogue order, with reasons.

    A capability-free read (camera-manager.md D2), so this runs on every
    adapter with no skip guard: "no" is an answer, never an exception. What it
    pins is that an adapter cannot quietly omit a view it does not implement —
    the panel gates each button on its entry, and a missing entry would be an
    enabled button that throws at runtime, exactly what hard rule 3 forbids.
    """
    manifest = await adapter.get_camera_support()

    assert isinstance(manifest, CameraSupportManifest)
    assert tuple(entry.view_id for entry in manifest.views) == CAMERA_VIEW_IDS, (
        "get_camera_support() must answer with exactly one entry per "
        "CAMERA_VIEW_IDS, in catalogue order"
    )
    for entry in manifest.views:
        if not entry.supported:
            assert entry.reason and entry.reason.strip(), (
                f"{adapter.name}: view {entry.view_id!r} is unsupported without a "
                "stated reason; the panel has nothing to show the instructor"
            )
    if not manifest.custom_positions_supported:
        assert manifest.custom_positions_reason and manifest.custom_positions_reason.strip(), (
            f"{adapter.name}: custom positions are unsupported without a stated reason"
        )


async def test_set_camera_view_is_accepted_for_every_supported_view(adapter: SimAdapter) -> None:
    """The flag's coverage entry (camera-manager.md §4.2).

    Every view the manifest advertises as supported can actually be selected.
    The manifest is the panel's only source of truth about which buttons are
    enabled, so a view that is advertised and then refuses is precisely the
    "capabilities, not failures" violation this suite exists to catch.
    """
    if not adapter.capabilities.can_control_camera:
        pytest.skip(f"{adapter.name} does not declare can_control_camera")

    supported = await _supported_view_ids(adapter)
    assert supported, (
        f"{adapter.name} declares can_control_camera but advertises no usable view; "
        "the capability and the manifest disagree"
    )
    try:
        for view_id in supported:
            await adapter.set_camera_view(view_id)
    finally:
        await _restore_camera(adapter)


async def test_camera_offset_round_trips(adapter: SimAdapter) -> None:
    """A free-camera pose written comes back unchanged.

    Only meaningful where the manifest reports ``custom_positions_supported``
    (camera-manager.md §4.2) — the named views and free positioning are
    separate reliability tiers on the same adapter (D3), and X-Plane's is the
    design's own central unknown (§10.2).

    Every field is asserted, not just one: the point of the round trip is that
    the adapter did not silently drop the angular half of the pose while
    honouring the translation — the shape the issue-#39 lesson took, that a
    value written into one call is not delivered until something reads it back
    at the other end.
    """
    if not adapter.capabilities.can_control_camera:
        pytest.skip(f"{adapter.name} does not declare can_control_camera")
    manifest = await adapter.get_camera_support()
    if not manifest.custom_positions_supported:
        pytest.skip(
            f"{adapter.name} does not support custom camera positions: "
            f"{manifest.custom_positions_reason}"
        )

    tol = CAMERA_OFFSET_TOLERANCE[adapter.name]
    offset = CameraOffset(
        forward_m=25.0,
        right_m=-10.0,
        up_m=8.0,
        look_offset_deg=45.0,
        pitch_deg=-12.0,
        zoom_ratio=1.5,
    )
    try:
        await adapter.set_camera_offset(offset)
        read_back = await adapter.get_camera_offset()

        assert read_back is not None, (
            f"{adapter.name} accepted a camera offset and then reported none; "
            "get_camera_offset() must answer with the pose the free camera sits at"
        )
        assert read_back.forward_m == pytest.approx(offset.forward_m, abs=tol)
        assert read_back.right_m == pytest.approx(offset.right_m, abs=tol)
        assert read_back.up_m == pytest.approx(offset.up_m, abs=tol)
        assert read_back.look_offset_deg == pytest.approx(offset.look_offset_deg, abs=tol)
        assert read_back.pitch_deg == pytest.approx(offset.pitch_deg, abs=tol)
        assert read_back.zoom_ratio == pytest.approx(offset.zoom_ratio, abs=tol)
    finally:
        await _restore_camera(adapter)


async def test_switching_view_clears_the_offset_read(adapter: SimAdapter) -> None:
    """A named view leaves no free-camera pose behind.

    ``get_camera_offset()`` reports the pose the *free* camera is at, so once a
    named view has been selected there is nothing meaningful left to report and
    ``None`` is the honest answer (camera-manager.md §4/§4.1). Without this,
    the panel would keep offering "save this position" for a pose the camera is
    no longer at.
    """
    if not adapter.capabilities.can_control_camera:
        pytest.skip(f"{adapter.name} does not declare can_control_camera")
    manifest = await adapter.get_camera_support()
    if not manifest.custom_positions_supported:
        pytest.skip(
            f"{adapter.name} does not support custom camera positions: "
            f"{manifest.custom_positions_reason}"
        )
    if CAMERA_RESTING_VIEW not in await _supported_view_ids(adapter):
        pytest.skip(f"{adapter.name} does not support the {CAMERA_RESTING_VIEW!r} view")

    try:
        await adapter.set_camera_offset(
            CameraOffset(forward_m=15.0, right_m=5.0, up_m=3.0, look_offset_deg=0.0, pitch_deg=0.0)
        )
        assert await adapter.get_camera_offset() is not None

        await adapter.set_camera_view(CAMERA_RESTING_VIEW)
        assert await adapter.get_camera_offset() is None, (
            f"{adapter.name} still reports a free-camera offset after switching to "
            f"the {CAMERA_RESTING_VIEW!r} view"
        )
    finally:
        await _restore_camera(adapter)


# --------------------------------------------------------------------------
# can_control_cockpit
# --------------------------------------------------------------------------

#: A second, minimal synthetic catalog used only by
#: :func:`test_swapping_the_aircraft_replaces_the_catalog` — a different
#: ``catalog_id`` and a single toggle, so the swap is unmistakably a
#: different aircraft rather than a mutated copy of ``fake-trainer``.
_FAKE_OTHER_DOCUMENT = CockpitCatalogDocument(
    aircraft=CockpitAircraft(catalog_id="fake-other", label="Fake other"),
    detect=CockpitDetection(dataref_exists="fake/other/present"),
    panels=[CockpitPanel(panel_id="p", label="P", order=0)],
    controls=[
        CockpitControlDefinition(
            control_id="only_switch",
            label="Only switch",
            panel_id="p",
            kind="toggle",
            readable=True,
            verified_on=datetime.date(2026, 9, 2),
            binding=CockpitBinding(press="fake/only_switch/press", read="fake/only_switch/status"),
        )
    ],
)


async def _first_control(
    adapter: SimAdapter, kind: CockpitControlKind, *, live_sweep: bool = True
) -> CockpitControlSpec | None:
    """The first actuable spec of ``kind`` in ``adapter``'s own active catalog.

    ``None`` when there is no active catalog, or none of ``kind`` marked
    ``live_sweep`` — the per-kind tests below skip on that, with the
    sentence §4.2 pins, which is only an ENVIRONMENTAL skip against a live
    simulator with an uncatalogued aircraft loaded (the ``grounded_adapter``
    precedent), never against the Fake — see
    :func:`test_fake_cockpit_catalog_has_a_live_sweep_control_of_every_kind`.
    """
    catalog = await adapter.get_cockpit_catalog()
    for spec in catalog.controls:
        if spec.kind == kind and (not live_sweep or spec.live_sweep):
            return spec
    return None


def _cockpit_readback_tolerance(adapter_name: str, spec: CockpitControlSpec) -> float:
    tolerance = COCKPIT_READBACK_TOLERANCE[adapter_name]
    return spec.readback_tolerance if tolerance is None else tolerance


def _require_numeric(value: CockpitValue | None) -> float:
    """Narrow a possibly-``None`` cockpit read-back to a float.

    Fails loudly rather than silently coercing ``None`` — every call site
    only reaches this after selecting a ``readable`` dial/encoder via
    :func:`_first_control`, so a ``None`` here is a real adapter bug, not an
    expected case to swallow.
    """
    assert value is not None, "expected a numeric cockpit read-back, got None"
    return float(value)


#: Every control kind, precisely typed — a bare ``tuple[str, ...]`` loop
#: variable would not satisfy :func:`_first_control`'s
#: ``CockpitControlKind`` parameter without a per-call ``# type: ignore``.
_ALL_CONTROL_KINDS: tuple[CockpitControlKind, ...] = (
    "toggle",
    "press",
    "dial",
    "encoder",
    "selector",
)


async def test_fake_cockpit_catalog_has_a_live_sweep_control_of_every_kind() -> None:
    """The mechanical proof that the per-kind skips below are never vacuous
    against the Fake. ``FakeSimAdapter`` declares ``can_control_cockpit``
    (:func:`test_fake_adapter_declares_every_capability`) and its synthetic
    catalog (§4.1) covers every kind with at least one ``live_sweep`` entry
    — a broken Fake catalog would otherwise turn all five per-kind tests
    into silent, always-passing skips instead of real assertions.
    """
    sim = FakeSimAdapter()
    await sim.connect()
    try:
        for kind in _ALL_CONTROL_KINDS:
            spec = await _first_control(sim, kind)
            assert spec is not None, f"fake-trainer has no live_sweep {kind!r} control"
    finally:
        await sim.disconnect()


async def test_actuate_toggle_round_trips(adapter: SimAdapter) -> None:
    """The flag's coverage entry (§4.2).

    Guarded-toggle rule (research §1): actuating the value already in place
    performs no press — ``actions_taken`` is 0 the second time.
    """
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    spec = await _first_control(adapter, "toggle")
    if spec is None:
        pytest.skip(
            f"{adapter.name}: the active cockpit catalog has no toggle control marked live_sweep"
        )

    before = (await adapter.read_cockpit_states([spec.control_id])).states[0].value
    # A toggle is *published* as a bool, on every adapter — the X-Plane read binding is
    # a float dataref (`1.0`), and `1.0 == True` is how this assertion passed silently
    # while the generic Cockpit panel showed "Unknown" for every live toggle (#253).
    assert isinstance(before, bool), f"{spec.control_id} read back {before!r}, not a bool"
    original = before
    target = not original
    try:
        flipped = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=target)
        )
        assert isinstance(flipped.state.value, bool)
        assert flipped.state.value == target
        assert flipped.actions_taken == 1

        unchanged = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=target)
        )
        assert unchanged.actions_taken == 0
        assert unchanged.state.value == target
    finally:
        await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=original)
        )


async def test_actuate_dial_round_trips(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    spec = await _first_control(adapter, "dial")
    if spec is None:
        pytest.skip(
            f"{adapter.name}: the active cockpit catalog has no dial control marked live_sweep"
        )
    assert spec.min_value is not None
    assert spec.max_value is not None
    assert spec.step is not None
    tolerance = _cockpit_readback_tolerance(adapter.name, spec)

    original = _require_numeric(
        (await adapter.read_cockpit_states([spec.control_id])).states[0].value
    )
    target = (
        original + spec.step if original + spec.step <= spec.max_value else original - spec.step
    )
    try:
        result = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=target)
        )
        assert _require_numeric(result.state.value) == pytest.approx(target, abs=tolerance)
        confirmed = (await adapter.read_cockpit_states([spec.control_id])).states[0].value
        assert _require_numeric(confirmed) == pytest.approx(target, abs=tolerance)
    finally:
        await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=original)
        )


async def test_actuate_selector_round_trips(adapter: SimAdapter) -> None:
    """Cycle to the option after the current one, wrapping to the first."""
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    spec = await _first_control(adapter, "selector")
    if spec is None:
        pytest.skip(
            f"{adapter.name}: the active cockpit catalog has no selector control marked live_sweep"
        )
    assert spec.options is not None
    values = [option.value for option in spec.options]

    original = (await adapter.read_cockpit_states([spec.control_id])).states[0].value
    # A live adapter's Web API reports every numeric dataref as a JSON float,
    # never a Python int — the same disease #247/#248 fixed in core.cockpit
    # (preconditions._condition_satisfied / actuation.selector_index). Reuse
    # selector_index itself rather than re-deriving its tolerant match here,
    # so this still genuinely proves "the read-back is one of the declared
    # options", not a loosened re-implementation of that check.
    current_index = selector_index(spec, original)
    assert current_index is not None, (
        f"{adapter.name}: read-back {original!r} for {spec.control_id!r} is not "
        f"among its declared options {values!r}"
    )
    target = values[(current_index + 1) % len(values)]
    try:
        result = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=target)
        )
        assert result.state.value == target
    finally:
        await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=original)
        )


async def test_actuate_encoder_moves_by_delta(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    spec = await _first_control(adapter, "encoder")
    if spec is None:
        pytest.skip(
            f"{adapter.name}: the active cockpit catalog has no encoder control marked live_sweep"
        )
    assert spec.step is not None
    tolerance = _cockpit_readback_tolerance(adapter.name, spec)

    original: float | None = None
    if spec.readable:
        value = (await adapter.read_cockpit_states([spec.control_id])).states[0].value
        original = _require_numeric(value)

    try:
        up = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, delta=2)
        )
        if spec.readable:
            assert original is not None
            assert _require_numeric(up.state.value) == pytest.approx(
                original + 2 * spec.step, abs=tolerance
            )
        else:
            assert up.state.value is None
    finally:
        down = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, delta=-2)
        )
        if spec.readable:
            assert original is not None
            assert _require_numeric(down.state.value) == pytest.approx(original, abs=tolerance)
        else:
            assert down.state.value is None


async def test_press_control_is_accepted(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    spec = await _first_control(adapter, "press")
    if spec is None:
        pytest.skip(
            f"{adapter.name}: the active cockpit catalog has no press control marked live_sweep"
        )

    result = await adapter.actuate_cockpit_control(CockpitActuation(control_id=spec.control_id))
    assert result.actions_taken == 1
    assert result.state.value is None


async def test_actuate_refuses_unmet_precondition(adapter: SimAdapter) -> None:
    """§4.2. Against the Fake this is exactly ``hdg_sel`` gated on
    ``fd_capt``/``cmd_a`` (research §2's finding, reproduced here in CI).

    Restricted to controls whose every referenced precondition control is a
    toggle (§4.2's own carve-out: "only if every one of them is a
    toggle/selector the test can safely restore") — a selector-gated
    precondition is left to a catalog-specific live test.
    """
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    catalog = await adapter.get_cockpit_catalog()
    spec = next((entry for entry in catalog.controls if entry.preconditions), None)
    if spec is None:
        pytest.skip(f"{adapter.name}: the active cockpit catalog has no control with preconditions")
    group = spec.preconditions[0]
    referenced_ids = [condition.control_id for condition in group.any_of]
    referenced_specs = {
        entry.control_id: entry for entry in catalog.controls if entry.control_id in referenced_ids
    }
    if any(entry.kind != "toggle" for entry in referenced_specs.values()):
        pytest.skip(
            f"{adapter.name}: this precondition references a non-toggle control the "
            "test cannot safely drive and restore"
        )

    own_before = (await adapter.read_cockpit_states([spec.control_id])).states[0].value
    referenced_originals = {
        control_id: (await adapter.read_cockpit_states([control_id])).states[0].value
        for control_id in referenced_ids
    }
    try:
        for control_id in referenced_ids:
            await adapter.actuate_cockpit_control(
                CockpitActuation(control_id=control_id, value=False)
            )

        with pytest.raises(CockpitPreconditionUnmet) as excinfo:
            await adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=True)
            )
        assert group.hint in str(excinfo.value)

        after_refusal = (await adapter.read_cockpit_states([spec.control_id])).states[0].value
        assert after_refusal == own_before

        satisfy_id = referenced_ids[0]
        await adapter.actuate_cockpit_control(CockpitActuation(control_id=satisfy_id, value=True))
        result = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=True)
        )
        assert result.state.value is True
    finally:
        # The control itself is gated by the same precondition it is being
        # restored from, so it must go back BEFORE the referenced controls
        # that satisfy it — restoring fd_capt/cmd_a first would make turning
        # hdg_sel back off raise the very error this test exists to prove.
        #
        # A live adapter reports every toggle read-back as a JSON float (e.g.
        # 1.0/0.0), never a Python bool, while validate_actuation's toggle
        # branch (§2.2) requires an actual bool — the identical #247/#248
        # disease, here in this test's own restore step (own_before and every
        # referenced_originals value are both raw toggle read-backs). Restore
        # with the coerced value, using is_on's own tolerant convention.
        await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id, value=is_on(own_before, on_value=1.0))
        )
        for control_id, original_value in referenced_originals.items():
            await adapter.actuate_cockpit_control(
                CockpitActuation(control_id=control_id, value=is_on(original_value, on_value=1.0))
            )


async def test_read_cockpit_states_reports_requested_ids_only(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    catalog = await adapter.get_cockpit_catalog()
    if catalog.aircraft is None:
        pytest.skip(f"{adapter.name}: no cockpit catalog is active for the loaded aircraft")

    readable_ids = [spec.control_id for spec in catalog.controls if spec.readable]
    if len(readable_ids) < 2:
        pytest.skip(f"{adapter.name}: the active catalog has fewer than two readable controls")
    a_id, b_id = readable_ids[0], readable_ids[1]

    scoped = await adapter.read_cockpit_states([a_id, b_id])
    assert [state.control_id for state in scoped.states] == [a_id, b_id]

    everything = await adapter.read_cockpit_states()
    assert {state.control_id for state in everything.states} == set(readable_ids)
    assert len(everything.states) == len(readable_ids)

    non_readable_ids = [spec.control_id for spec in catalog.controls if not spec.readable]
    if non_readable_ids:
        one = await adapter.read_cockpit_states([non_readable_ids[0]])
        assert one.states[0].value is None


async def test_actuate_unknown_control_raises(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    catalog = await adapter.get_cockpit_catalog()
    if catalog.aircraft is None:
        pytest.skip(f"{adapter.name}: no cockpit catalog is active for the loaded aircraft")

    with pytest.raises(CockpitControlUnknown):
        await adapter.actuate_cockpit_control(CockpitActuation(control_id="no_such_control"))

    if not catalog.parked:
        pytest.skip(f"{adapter.name}: the active catalog has no parked entries")
    parked = catalog.parked[0]
    with pytest.raises(CockpitControlUnknown) as excinfo:
        await adapter.actuate_cockpit_control(
            CockpitActuation(control_id=parked.control_id, value=True)
        )
    assert parked.reason in str(excinfo.value)


async def test_actuate_rejects_kind_mismatch(adapter: SimAdapter) -> None:
    """§2.2's mismatch table, against whichever kinds the active catalog has.
    Nothing is ever written: every case is verified unchanged afterwards."""
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    catalog = await adapter.get_cockpit_catalog()
    if catalog.aircraft is None:
        pytest.skip(f"{adapter.name}: no cockpit catalog is active for the loaded aircraft")

    by_kind: dict[str, CockpitControlSpec] = {}
    for entry in catalog.controls:
        by_kind.setdefault(entry.kind, entry)

    cases: list[tuple[CockpitControlSpec, CockpitActuation]] = []
    if "dial" in by_kind:
        dial = by_kind["dial"]
        assert dial.max_value is not None
        cases.append((dial, CockpitActuation(control_id=dial.control_id, value=True)))
        cases.append(
            (dial, CockpitActuation(control_id=dial.control_id, value=dial.max_value + 1_000_000.0))
        )
    if "toggle" in by_kind:
        toggle = by_kind["toggle"]
        cases.append((toggle, CockpitActuation(control_id=toggle.control_id, delta=1)))
    if "encoder" in by_kind:
        encoder = by_kind["encoder"]
        cases.append((encoder, CockpitActuation(control_id=encoder.control_id, value=1.0)))
    if "press" in by_kind:
        press = by_kind["press"]
        cases.append((press, CockpitActuation(control_id=press.control_id, value=True)))
    if not cases:
        pytest.skip(f"{adapter.name}: not enough kinds in the active catalog for a mismatch case")

    for entry, actuation in cases:
        before = None
        if entry.readable:
            before = (await adapter.read_cockpit_states([entry.control_id])).states[0].value
        with pytest.raises(ValueError, match=r".*"):
            await adapter.actuate_cockpit_control(actuation)
        if entry.readable:
            after = (await adapter.read_cockpit_states([entry.control_id])).states[0].value
            assert after == before


async def test_refresh_bumps_the_revision(adapter: SimAdapter) -> None:
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    before = await adapter.get_cockpit_catalog()
    refreshed = await adapter.refresh_cockpit_catalog()
    assert refreshed.revision > before.revision

    after = await adapter.get_cockpit_catalog()
    assert after.revision == refreshed.revision
    if before.aircraft is not None:
        assert refreshed.aircraft is not None
        assert refreshed.aircraft.catalog_id == before.aircraft.catalog_id


async def test_cockpit_state_and_result_carry_the_revision(adapter: SimAdapter) -> None:
    """The UI's swap detector (D13): a snapshot and an actuation result both
    name the revision they were taken/applied against."""
    if not adapter.capabilities.can_control_cockpit:
        pytest.skip(f"{adapter.name} does not declare can_control_cockpit")
    catalog = await adapter.get_cockpit_catalog()
    if catalog.aircraft is None:
        pytest.skip(f"{adapter.name}: no cockpit catalog is active for the loaded aircraft")

    states = await adapter.read_cockpit_states()
    assert states.revision == catalog.revision

    spec = await _first_control(adapter, "toggle")
    if spec is None:
        pytest.skip(
            f"{adapter.name}: the active cockpit catalog has no toggle control marked live_sweep"
        )
    current = (await adapter.read_cockpit_states([spec.control_id])).states[0].value
    # A no-op actuation (request the value already in place) needs no restore.
    result = await adapter.actuate_cockpit_control(
        CockpitActuation(control_id=spec.control_id, value=bool(current))
    )
    assert result.actions_taken == 0
    assert result.revision == catalog.revision


async def test_swapping_the_aircraft_replaces_the_catalog() -> None:
    """Fake-only, via the ``load_cockpit_catalog`` test affordance (§4.1) —
    the CI-visible surface of "the aircraft was swapped"."""
    sim = FakeSimAdapter()
    await sim.connect()
    try:
        original = await sim.get_cockpit_catalog()
        assert original.aircraft is not None
        original_control_id = original.controls[0].control_id

        sim.load_cockpit_catalog(_FAKE_OTHER_DOCUMENT)
        swapped = await sim.get_cockpit_catalog()
        assert swapped.aircraft is not None
        assert swapped.aircraft.catalog_id == "fake-other"
        assert swapped.revision > original.revision

        with pytest.raises(CockpitControlUnknown):
            await sim.read_cockpit_states([original_control_id])

        sim.load_cockpit_catalog(None)
        cleared = await sim.get_cockpit_catalog()
        assert cleared.aircraft is None

        empty_states = await sim.read_cockpit_states()
        assert empty_states.catalog_id is None

        with pytest.raises(CockpitCatalogInactive):
            await sim.actuate_cockpit_control(
                CockpitActuation(control_id="only_switch", value=True)
            )
    finally:
        await sim.disconnect()


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


async def test_traffic_methods_refuse_without_the_capability() -> None:
    """Roadmap Phase 3 exit criterion 3, the CI-provable half (ai-traffic.md D14).

    The criterion's own wording: *"With the bridge not installed, the
    application starts, every non-traffic feature works, and traffic controls
    are disabled with a stated reason — verified by a test running against an
    adapter declaring ``can_spawn_traffic = False``."* This is that test at the
    adapter seam, in CI, with no simulator and no bridge:

    * every traffic *write* refuses with :class:`CapabilityNotSupported`
      naming the missing flag — the stated reason;
    * the *reads* degrade instead of failing: ``get_traffic_contacts()``
      returns ``()`` and ``stream_traffic`` yields ``()`` forever, so nothing
      that merely observes traffic (the WS route, the map) needs the flag.
      That is a capability check, not a green-wash: "no traffic" is the honest
      answer for an adapter that cannot spawn any.
    """

    class NoTrafficAdapter(FakeSimAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_spawn_traffic": False})

    sim = NoTrafficAdapter()
    await sim.connect()
    try:
        anchor = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=5000.0)
        with pytest.raises(CapabilityNotSupported, match="can_spawn_traffic"):
            await sim.spawn_traffic(_traffic_track(anchor))
        with pytest.raises(CapabilityNotSupported, match="can_spawn_traffic"):
            await sim.despawn_traffic("no-such-id")
        with pytest.raises(CapabilityNotSupported, match="can_spawn_traffic"):
            await sim.clear_all_traffic()

        assert await sim.get_traffic_contacts() == ()

        stream = sim.stream_traffic(STREAM_INTERVAL_S)
        try:
            assert await anext(stream) == ()
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()
    finally:
        await sim.disconnect()


async def test_pushback_refuses_without_the_capability() -> None:
    """The other half of the flag's contract (pushback-manager.md §4.2).

    ``FakeSimAdapter`` declares every capability
    (:func:`test_fake_adapter_declares_every_capability`), so a
    skip-guarded case against the parametrised ``adapter``/``grounded_adapter``
    fixtures would never actually exercise this refusal — the same reasoning
    the weather/failures/loadout/traffic refusal tests above already state.
    The restricted-subclass pattern is unaffected by ``on_ground``: a refusal
    is raised before the precondition is even checked.
    """

    class NoPushbackAdapter(FakeSimAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_pushback": False})

    sim = NoPushbackAdapter(initial_state=GROUNDED_FAKE_STATE)
    await sim.connect()
    try:
        request = PushbackRequest(direction="straight", distance_m=20.0)
        with pytest.raises(CapabilityNotSupported, match="can_pushback"):
            await sim.pushback(request)
    finally:
        await sim.disconnect()


async def test_camera_methods_refuse_without_the_capability() -> None:
    """The refusal half of ``can_control_camera`` (camera-manager.md §4.2).

    ``FakeSimAdapter`` declares every capability
    (:func:`test_fake_adapter_declares_every_capability`), so a skip-guarded
    case against the parametrised ``adapter`` fixture would never actually
    exercise this — the same reasoning the weather/failures/loadout/traffic/
    pushback refusals above already state.

    The two *writes* raise; the two *reads* answer (D2/D6): a manifest with
    every view unsupported and a stated reason, and ``None`` for the offset.
    """

    class NoCameraAdapter(FakeSimAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_control_camera": False})

    sim = NoCameraAdapter()
    await sim.connect()
    try:
        with pytest.raises(CapabilityNotSupported, match="can_control_camera"):
            await sim.set_camera_view("cockpit")
        with pytest.raises(CapabilityNotSupported, match="can_control_camera"):
            await sim.set_camera_offset(
                CameraOffset(
                    forward_m=10.0, right_m=0.0, up_m=5.0, look_offset_deg=0.0, pitch_deg=0.0
                )
            )

        manifest = await sim.get_camera_support()
        assert tuple(entry.view_id for entry in manifest.views) == CAMERA_VIEW_IDS
        assert all(not entry.supported for entry in manifest.views)
        assert all(entry.reason for entry in manifest.views)
        assert manifest.custom_positions_supported is False
        assert manifest.custom_positions_reason
        assert await sim.get_camera_offset() is None
    finally:
        await sim.disconnect()


async def test_offset_methods_refuse_without_custom_positions_support() -> None:
    """Custom positioning is gated by the manifest, not by a second flag (D3).

    An adapter can perfectly well fire the named-view commands and still have
    no way to place a free camera — the design's own expectation for X-Plane
    until the §10.2 spike resolves. That case is expressed as
    ``custom_positions_supported=False`` on a manifest whose views *are*
    supported, and it must refuse ``set_camera_offset`` while leaving
    ``set_camera_view`` completely unaffected.
    """

    reason = "This adapter cannot place a free camera."

    class NoCustomPositionsAdapter(FakeSimAdapter):
        async def get_camera_support(self) -> CameraSupportManifest:
            manifest = await super().get_camera_support()
            return manifest.model_copy(
                update={
                    "custom_positions_supported": False,
                    "custom_positions_reason": reason,
                }
            )

    sim = NoCustomPositionsAdapter()
    await sim.connect()
    try:
        manifest = await sim.get_camera_support()
        assert all(entry.supported for entry in manifest.views)
        assert manifest.custom_positions_supported is False
        assert manifest.custom_positions_reason == reason

        with pytest.raises(CapabilityNotSupported, match="can_control_camera"):
            await sim.set_camera_offset(
                CameraOffset(
                    forward_m=10.0, right_m=0.0, up_m=5.0, look_offset_deg=0.0, pitch_deg=0.0
                )
            )

        # The named views are untouched by the offset refusal.
        for view_id in CAMERA_VIEW_IDS:
            await sim.set_camera_view(view_id)
        assert await sim.get_camera_offset() is None
    finally:
        await sim.disconnect()


async def test_cockpit_methods_refuse_without_the_capability() -> None:
    """The refusal half of ``can_control_cockpit`` (cockpit-control-catalog.md §4.2).

    ``FakeSimAdapter`` declares every capability
    (:func:`test_fake_adapter_declares_every_capability`), so a skip-guarded
    case against the parametrised ``adapter`` fixture would never actually
    exercise this — the same reasoning every other capability's refusal test
    in this cluster already states.

    The three *writes*/mutating reads raise; ``get_cockpit_catalog`` is
    capability-free (D1) and answers ``supported=False`` with a reason
    instead.
    """

    class NoCockpitAdapter(FakeSimAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_control_cockpit": False})

    sim = NoCockpitAdapter()
    await sim.connect()
    try:
        with pytest.raises(CapabilityNotSupported, match="can_control_cockpit"):
            await sim.refresh_cockpit_catalog()
        with pytest.raises(CapabilityNotSupported, match="can_control_cockpit"):
            await sim.read_cockpit_states()
        with pytest.raises(CapabilityNotSupported, match="can_control_cockpit"):
            await sim.actuate_cockpit_control(CockpitActuation(control_id="fd_capt", value=True))

        catalog = await sim.get_cockpit_catalog()
        assert catalog.supported is False
        assert catalog.reason
        assert catalog.aircraft is None
    finally:
        await sim.disconnect()
