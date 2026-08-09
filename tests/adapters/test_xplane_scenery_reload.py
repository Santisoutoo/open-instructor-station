"""Repositioning across a scenery reload, pinned in CI — issue #36.

A teleport long enough to make X-Plane load new scenery moves the origin of the
local OpenGL frame. The coordinates written before the reload then denote a
*different* place on earth, so the aircraft ends up somewhere it was never sent
and the arrival poll can never converge: Madrid to Heathrow spent the full 30 s
budget and raised, with every write accepted.

Nothing in the existing suites can see that. ``FakeSimAdapter`` has no local
frame at all — it stores latitude and longitude — and the recording stub in
``test_xplane_freeze_protocol.py`` stores dataref values in a dict, so what it
reads back is whatever was written and no frame can move underneath it. This
file therefore brings a third kind of stand-in: a **simulator that keeps its
aircraft in a local frame and derives the world coordinates from it**, exactly
as X-Plane does, and that relocates the frame the way a scenery reload does.

That is the only honest way to test this in CI. Giving ``FakeSimAdapter`` a
local frame was the alternative and was rejected: the frame is an X-Plane
mechanic, the Fake is the sim-agnostic reference implementation, and the
``SimAdapter`` contract says nothing about how an adapter stores a position —
same reasoning that keeps ``frozen_flight_model`` out of the protocol.

Only the wire is replaced. The freeze discipline, the re-aim loop, the settle
criterion and the arrival check are the real adapter's code running unmodified.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adapters.xplane import xplane_adapter
from adapters.xplane.xplane_adapter import (
    POSITION_WRITE_TOLERANCE_M,
    XPlaneRepositionFailed,
    XPlaneSimAdapter,
)
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.local_frame import (
    LocalCoordinates,
    LocalFrameOrigin,
    local_to_world,
    origin_separation_m,
    world_to_local,
)
from core.models import GeoPosition

_METRES_PER_FOOT = 0.3048

#: Where the stub's aircraft starts: LEMD, 2 000 ft.
HOME = GeoPosition(latitude=40.4936, longitude=-3.5668, altitude_ft=2000.0)

#: The frame X-Plane had anchored at LEMD on the 2026-08-06 validation run — a
#: whole-degree point 38.7 km from the aircraft, with a small vertical datum
#: offset. Real numbers, so the stub's geometry is the geometry that was
#: measured rather than a convenient zero.
HOME_ORIGIN = LocalFrameOrigin(latitude=40.5, longitude=-4.0, vertical_offset_m=-0.61)

#: A hop that stays inside the loaded scenery: nothing reloads, nothing moves.
SHORT_HOP_NM = 5.0

#: A hop that leaves it. Madrid to Heathrow is ~675 NM; 200 NM provokes the same
#: event with numbers that stay readable, and the stub's trigger is set below it.
LONG_HAUL_NM = 200.0

#: How far the stub lets its aircraft get from the anchor before it reloads.
RELOAD_TRIGGER_M = 100_000.0

#: Frames the stub spends loading scenery, during which it publishes nothing
#: new. This is the trap the settle criterion exists for: the local coordinates
#: already read back as the newly written ones while the world coordinates are
#: still the old ones, so an origin measured across the pair during the stall is
#: not merely stale — it is fabricated, off by the whole length of the teleport.
RELOAD_STALL_FRAMES = 10

#: Frames between a local-frame write and the world coordinates derived from it.
#: One or two in the real sim; the arrival poll is what absorbs it.
PUBLISH_LAG_FRAMES = 2


class _FrameShiftingXPlane(XPlaneSimAdapter):
    """A stand-in X-Plane that stores a local frame and can relocate it.

    The aircraft's authoritative position is :attr:`local`, in the frame
    :attr:`origin`. ``latitude``/``longitude``/``elevation`` are *derived* from
    those on the stub's frame tick, never stored — which is the property that
    makes an origin shift observable at all.

    A reload is **armed** when a placement finishes with the aircraft farther
    from the anchor than ``reload_trigger_m``, and fires on the next frame. It
    re-anchors the frame on the scenery that has just been loaded and leaves the
    aircraft's local coordinates untouched, so those coordinates now denote a
    different world position. That is the defect in issue #36, stated as a rule.

    Arming on a *completed* placement rather than on each of the three
    coordinate writes is deliberate: a frame that moves between ``local_x`` and
    ``local_z`` is a different, unreported failure, and modelling it here would
    be inventing a bug to fix.
    """

    def __init__(
        self,
        *,
        reloads_available: int = 1,
        reload_trigger_m: float = RELOAD_TRIGGER_M,
        accepts_position_writes: bool = True,
    ) -> None:
        super().__init__()
        self.origin = HOME_ORIGIN
        self.local = world_to_local(HOME_ORIGIN, HOME)
        self.published = HOME
        self.reloads_available = reloads_available
        self.reload_trigger_m = reload_trigger_m
        self.accepts_position_writes = accepts_position_writes
        #: Reloads the stub has actually performed.
        self.reloads = 0
        #: Placements the adapter has written, counted at ``local_x``.
        self.placements = 0
        self.writes: list[tuple[str, Any]] = []
        self.commands: list[str] = []
        self._reload_armed = False
        self._stalled_frames = 0
        self.values: dict[str, Any] = {
            "psi": 0.0,
            "theta": 0.0,
            "phi": 0.0,
            "indicated_airspeed": 120.0,
            "vh_ind_fpm": 0.0,
            "on_ground": 0,
            "temperature_ambient_deg_c": 15.0,
            "local_vx": 0.0,
            "local_vy": 0.0,
            "local_vz": 0.0,
            "override_planepath": 0,
            "has_crashed": 0,
        }

    @property
    def is_connected(self) -> bool:
        """Always connected: there is no handshake to perform against an object."""
        return True

    @property
    def anchor(self) -> GeoPosition:
        """Where the frame is currently anchored, as a position."""
        return GeoPosition(latitude=self.origin.latitude, longitude=self.origin.longitude)

    @property
    def written_keys(self) -> list[str]:
        """The datarefs written, in order, with duplicates kept."""
        return [key for key, _ in self.writes]

    # -- The simulator's frame loop ----------------------------------------

    def _run_a_frame(self) -> None:
        """Recompute the derived world coordinates, and reload scenery if due.

        Runs on every read, which is the closest a stub with no clock can get to
        "once a frame". A stalled sim answers reads without advancing anything,
        which is precisely the state a naive re-measure would be fooled by.
        """
        if self._stalled_frames > 0:
            self._stalled_frames -= 1
            return
        if self._reload_armed:
            self._reload_armed = False
            self._reload_scenery()
            return
        self.published = local_to_world(self.origin, self.local)

    def _reload_scenery(self) -> None:
        """Relocate the frame onto the newly loaded scenery, aircraft included.

        The anchor moves to where the aircraft was *commanded*; the aircraft's
        local coordinates do not, so once the stall is over it is published
        somewhere else entirely.
        """
        self.reloads += 1
        commanded = local_to_world(self.origin, self.local)
        self.origin = LocalFrameOrigin(
            latitude=commanded.latitude,
            longitude=commanded.longitude,
            vertical_offset_m=self.origin.vertical_offset_m,
        )
        self._stalled_frames = RELOAD_STALL_FRAMES

    # -- The wire -----------------------------------------------------------

    async def _read(self, key: str) -> Any:
        self._run_a_frame()
        if key == "latitude":
            return self.published.latitude
        if key == "longitude":
            return self.published.longitude
        if key == "elevation":
            return self.published.altitude_ft * _METRES_PER_FOOT
        if key == "local_x":
            return self.local.x_m
        if key == "local_y":
            return self.local.y_m
        if key == "local_z":
            return self.local.z_m
        return self.values[key]

    async def _write(self, key: str, value: float | int | bool, index: int | None = None) -> None:
        self.writes.append((key, value))
        if key not in ("local_x", "local_y", "local_z"):
            self.values[key] = value
            return
        if key == "local_x":
            self.placements += 1
        if not self.accepts_position_writes:
            return
        self.local = self.local.model_copy(update={f"{key[-1]}_m": float(value)})
        self._stalled_frames = max(self._stalled_frames, PUBLISH_LAG_FRAMES)
        if key == "local_z":
            self._arm_reload_if_the_aircraft_left_the_scenery()

    def _arm_reload_if_the_aircraft_left_the_scenery(self) -> None:
        """A completed placement outside the loaded area schedules a reload."""
        if self.reloads >= self.reloads_available:
            return
        commanded = local_to_world(self.origin, self.local)
        distance_nm, _ = distance_and_bearing(self.anchor, commanded)
        if distance_nm * METRES_PER_NAUTICAL_MILE > self.reload_trigger_m:
            self._reload_armed = True

    async def _activate(self, key: str) -> None:
        self.commands.append(key)

    # -- Assertions read through these ---------------------------------------

    async def settled_position(self) -> GeoPosition:
        """Where the aircraft ends up once the stub has no work left to do."""
        for _ in range(RELOAD_STALL_FRAMES + PUBLISH_LAG_FRAMES + 2):
            self._run_a_frame()
        return self.published


@pytest.fixture(autouse=True)
def _fast_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compress the adapter's waits without changing what they mean.

    Every constant keeps its *relationship* to the others, which is what the
    logic under test depends on: an arrival slice is still many polls long, so
    the publication lag and the reload stall are still absorbed inside one, and
    the total budget is still several slices. Only the wall clock shrinks —
    there is no simulator here to give a physics frame to.
    """
    monkeypatch.setattr(xplane_adapter, "_OVERRIDE_SETTLE_S", 0.0)
    monkeypatch.setattr(xplane_adapter, "_RELEASE_SETTLE_S", 0.0)
    monkeypatch.setattr(xplane_adapter, "_ARRIVAL_POLL_S", 0.0)
    monkeypatch.setattr(xplane_adapter, "_ARRIVAL_ATTEMPT_S", 0.05)
    monkeypatch.setattr(xplane_adapter, "_REPOSITION_TIMEOUT_S", 2.0)
    monkeypatch.setattr(xplane_adapter, "_ORIGIN_SAMPLE_S", 0.0)


def target_at(distance_nm: float, bearing_deg: float = 270.0) -> GeoPosition:
    """A teleport target ``distance_nm`` from :data:`HOME`, at the same altitude."""
    moved = point_at_distance_and_bearing(HOME, distance_nm, bearing_deg)
    return GeoPosition(
        latitude=moved.latitude,
        longitude=moved.longitude,
        altitude_ft=HOME.altitude_ft,
    )


def error_m(position: GeoPosition, target: GeoPosition) -> float:
    """Horizontal distance between two positions, in metres."""
    distance_nm, _ = distance_and_bearing(position, target)
    return distance_nm * METRES_PER_NAUTICAL_MILE


def _far_future() -> float:
    """A deadline the settle loop will never reach."""
    return asyncio.get_running_loop().time() + 3600.0


def _in_the_past() -> float:
    """A deadline that has already expired."""
    return asyncio.get_running_loop().time() - 1.0


# --------------------------------------------------------------------------
# The stand-in itself — an assertion is only worth what its stub is
# --------------------------------------------------------------------------


async def test_the_stub_derives_the_world_position_from_the_local_frame() -> None:
    """Reading back a written local coordinate must move the aircraft's lat/lon.

    If this fails, every other test in this file is measuring a dictionary.
    """
    sim = _FrameShiftingXPlane()

    state = await sim.get_aircraft_state()
    assert error_m(GeoPosition(latitude=state.latitude, longitude=state.longitude), HOME) < 1.0

    east = world_to_local(HOME_ORIGIN, target_at(SHORT_HOP_NM, bearing_deg=90.0))
    await sim._write("local_x", east.x_m)
    await sim._write("local_y", east.y_m)
    await sim._write("local_z", east.z_m)

    settled = await sim.settled_position()
    assert error_m(settled, target_at(SHORT_HOP_NM, bearing_deg=90.0)) < 1.0


async def test_the_stub_reproduces_the_defect_being_fixed() -> None:
    """One aim into a frame that then moves lands the aircraft somewhere else.

    This is issue #36 without the adapter in the way: coordinates computed in
    the frame that was current, accepted by the sim, and denoting a completely
    different place by the time the reload has finished.
    """
    sim = _FrameShiftingXPlane()
    target = target_at(LONG_HAUL_NM)

    aimed = world_to_local(sim.origin, target)
    await sim._write("local_x", aimed.x_m)
    await sim._write("local_y", aimed.y_m)
    await sim._write("local_z", aimed.z_m)

    settled = await sim.settled_position()

    assert sim.reloads == 1, "the long haul did not provoke a reload"
    assert error_m(settled, target) > 100_000.0, (
        "the stub's reload left the aircraft where it was sent, so it is not "
        "modelling the frame relocation this file exists to test"
    )
    assert origin_separation_m(HOME_ORIGIN, sim.origin) > RELOAD_TRIGGER_M


# --------------------------------------------------------------------------
# The fix
# --------------------------------------------------------------------------


async def test_a_long_haul_converges_across_a_scenery_reload() -> None:
    """The regression: ``set_position`` must arrive, not time out.

    Before the fix the adapter wrote once, polled a target the aircraft could
    never reach, and raised ``XPlaneRepositionFailed`` after the full budget.
    """
    sim = _FrameShiftingXPlane()
    target = target_at(LONG_HAUL_NM)

    await sim.set_position(target, heading_deg=270.0)

    assert sim.reloads == 1, "the fixture did not exercise a frame relocation"
    settled = await sim.settled_position()
    assert error_m(settled, target) <= POSITION_WRITE_TOLERANCE_M
    assert sim.placements == 2, (
        f"expected one aim, a re-measure and one re-aim; got {sim.placements} placements"
    )


async def test_the_re_aim_is_computed_in_the_frame_that_replaced_the_old_one() -> None:
    """The second placement must be expressed in the *new* frame, not the old.

    Rewriting the same coordinates would be a retry; what makes this converge is
    that the target is re-projected through a freshly measured origin.
    """
    sim = _FrameShiftingXPlane()
    target = target_at(LONG_HAUL_NM)
    first_frame = sim.origin

    await sim.set_position(target, heading_deg=270.0)

    aims = [
        LocalCoordinates(x_m=x, y_m=y, z_m=z)
        for (_, x), (_, y), (_, z) in zip(
            [write for write in sim.writes if write[0] == "local_x"],
            [write for write in sim.writes if write[0] == "local_y"],
            [write for write in sim.writes if write[0] == "local_z"],
            strict=True,
        )
    ]
    assert len(aims) == 2
    assert error_m(local_to_world(first_frame, aims[0]), target) < 1.0, (
        "the first aim was not the target in the frame that was current"
    )
    assert error_m(local_to_world(sim.origin, aims[1]), target) < 1.0, (
        "the re-aim was not the target in the frame that replaced it"
    )
    assert origin_separation_m(first_frame, sim.origin) > RELOAD_TRIGGER_M


async def test_the_re_aim_rewrites_the_velocity_vector_too() -> None:
    """The frame's axes rotate with its anchor, so the velocity moves with it.

    Left behind, the aircraft would be in the right place flying a heading it
    was never given: at these distances the meridians converge by degrees.
    """
    sim = _FrameShiftingXPlane()

    await sim.set_position(target_at(LONG_HAUL_NM), heading_deg=270.0)

    assert sim.written_keys.count("local_vx") == 2
    assert sim.written_keys.count("local_vz") == 2
    assert sim.written_keys.count("psi") == 2


async def test_a_short_hop_still_costs_exactly_one_placement() -> None:
    """Nothing reloads inside the loaded scenery, so nothing is re-aimed.

    The fix must not make the common case — a 5 NM repositioning onto a final —
    pay for the long-haul one with an extra write and an extra settle.
    """
    sim = _FrameShiftingXPlane()
    target = target_at(SHORT_HOP_NM)

    await sim.set_position(target, heading_deg=270.0)

    assert sim.reloads == 0
    assert sim.placements == 1
    assert error_m(await sim.settled_position(), target) <= POSITION_WRITE_TOLERANCE_M


# --------------------------------------------------------------------------
# The settle criterion — deciding *when* a re-measured origin can be trusted
# --------------------------------------------------------------------------


class _ScriptedOrigins(_FrameShiftingXPlane):
    """A stub whose frame origin follows a script, one entry per measurement.

    The frame itself is beside the point here: what is under test is how many
    measurements the adapter insists on before it aims with one, and which of
    them it comes back with.
    """

    def __init__(self, script: list[LocalFrameOrigin]) -> None:
        super().__init__()
        self.script = script
        self.measurements = 0

    async def measure_local_frame_origin(self) -> LocalFrameOrigin:
        index = min(self.measurements, len(self.script) - 1)
        self.measurements += 1
        return self.script[index]


def origin_at(latitude: float, longitude: float) -> LocalFrameOrigin:
    """A frame origin, spelled short enough to read a script off."""
    return LocalFrameOrigin(latitude=latitude, longitude=longitude)


async def test_a_moving_origin_is_not_aimed_with_until_it_stops() -> None:
    """One measurement cannot tell a settled frame from one caught mid-shift.

    The script relocates the frame twice before it comes to rest. Returning the
    first reading would aim the re-write with an origin that was already history
    — the same mistake as aiming with the pre-reload one, arrived at differently.
    """
    sim = _ScriptedOrigins(
        [
            origin_at(40.5, -4.0),  # where the frame was
            origin_at(45.0, -2.0),  # mid-shift
            origin_at(51.5, -0.5),  # where it came to rest
            origin_at(51.5, -0.5),
            origin_at(51.5, -0.5),
        ]
    )

    settled = await sim._settled_local_frame_origin(deadline=_far_future())

    assert origin_separation_m(settled, origin_at(51.5, -0.5)) < 1.0
    assert sim.measurements == 5, (
        "the origin must be sampled until two consecutive readings agree, "
        f"and no more; it was sampled {sim.measurements} times"
    )


async def test_a_settled_origin_costs_the_minimum_number_of_samples() -> None:
    """A frame that never moved is confirmed in two extra round trips, not ten."""
    sim = _ScriptedOrigins([origin_at(40.5, -4.0)])

    settled = await sim._settled_local_frame_origin(deadline=_far_future())

    assert origin_separation_m(settled, origin_at(40.5, -4.0)) < 1.0
    assert sim.measurements == xplane_adapter._ORIGIN_STABLE_SAMPLES + 1


async def test_the_settle_gives_up_at_the_deadline_instead_of_hanging() -> None:
    """A frame that will not settle must not eat the budget it does not own.

    The verdict on a placement belongs to the arrival check, not to this: a
    deadline reached here hands back the latest reading and lets the caller
    aim with it, fail, and report honestly.
    """
    sim = _ScriptedOrigins([origin_at(40.0 + step, -4.0) for step in range(20)])

    settled = await sim._settled_local_frame_origin(deadline=_in_the_past())

    assert origin_separation_m(settled, origin_at(40.0, -4.0)) < 1.0
    assert sim.measurements == 1


class _StaleFirstMeasurement(_FrameShiftingXPlane):
    """A stub that answers the whole first settle from a frame in transition.

    The settle criterion is deliberately not infallible — a simulator stalled
    inside a reload can hold still and answer, and every reading taken then
    agrees with the last while describing a frame that is about to be replaced.
    This stub is that worst case, made deterministic: the first settle returns a
    consistent lie, so the re-aim goes to the wrong place and the adapter has to
    recover on the attempt after it.
    """

    #: Exactly one stability window's worth, so the lie is consistent for as
    #: long as the criterion looks at it and gone by the attempt after.
    _BOGUS_READINGS = xplane_adapter._ORIGIN_STABLE_SAMPLES + 1

    def __init__(self) -> None:
        super().__init__()
        self._bogus_left = self._BOGUS_READINGS

    async def measure_local_frame_origin(self) -> LocalFrameOrigin:
        truth = await super().measure_local_frame_origin()
        if self.reloads == 0 or self._bogus_left <= 0:
            return truth
        self._bogus_left -= 1
        # Three degrees of latitude out: ~330 km, so the placement it produces
        # misses by far more than any tolerance, and stably enough that a
        # stability window on its own is fooled by it.
        return LocalFrameOrigin(
            latitude=truth.latitude + 3.0,
            longitude=truth.longitude,
            vertical_offset_m=truth.vertical_offset_m,
        )


async def test_a_settle_that_was_fooled_still_converges_on_the_next_attempt() -> None:
    """This is what the third attempt is for, and why the bound is not two.

    The arrival check is the only thing in the loop that cannot be fooled: it
    reads the world position X-Plane derives from whichever frame is current. A
    bad origin therefore costs one more attempt and never a false success.
    """
    sim = _StaleFirstMeasurement()
    target = target_at(LONG_HAUL_NM)

    await sim.set_position(target, heading_deg=270.0)

    assert sim.placements == 3
    assert error_m(await sim.settled_position(), target) <= POSITION_WRITE_TOLERANCE_M


# --------------------------------------------------------------------------
# The bound — a retry loop with no end is a worse bug than the one it fixes
# --------------------------------------------------------------------------


async def test_a_placement_that_never_takes_gives_up_and_says_so() -> None:
    """Re-aiming must not turn a bounded failure into an unbounded one.

    A simulator that swallows position writes cannot be recovered from by aiming
    again, and the instructor is owed the failure rather than a spinner.
    """
    sim = _FrameShiftingXPlane(accepts_position_writes=False)

    with pytest.raises(XPlaneRepositionFailed, match="did not arrive"):
        await sim.set_position(target_at(LONG_HAUL_NM), heading_deg=270.0)

    assert sim.placements == xplane_adapter._MAX_REPOSITION_WRITES


async def test_the_five_step_procedure_survives_the_re_aim() -> None:
    """One freeze, one release, and the crash state cleared — however many aims.

    A leaked ``override_planepath`` freezes the user's aircraft with nothing in
    the UI to explain it, and the release has to survive a loop being wrapped
    around the writes it guards.
    """
    sim = _FrameShiftingXPlane()

    await sim.set_position(target_at(LONG_HAUL_NM), heading_deg=270.0)

    overrides = [value for key, value in sim.writes if key == "override_planepath"]
    assert overrides == [1, 0], f"expected one freeze and one release, got {sim.writes}"
    assert sim.writes[0] == ("override_planepath", 1)
    assert sim.writes[-1] == ("override_planepath", 0)
    assert sim.commands == ["fix_all_systems"]


async def test_the_override_comes_off_when_a_placement_fails() -> None:
    """Including on the path that gives up after re-aiming."""
    sim = _FrameShiftingXPlane(accepts_position_writes=False)

    with pytest.raises(XPlaneRepositionFailed):
        await sim.set_position(target_at(LONG_HAUL_NM), heading_deg=270.0)

    assert sim.writes[-1] == ("override_planepath", 0)
