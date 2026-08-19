"""What ``XPlaneSimAdapter.pushback()`` delegates, pinned in CI.

pushback-manager.md §5.1 specifies the method as four lines, and the notable
part is what is *absent*: no new dataref. The geometry is already covered by
``tests/core/test_pushback.py`` and the repositioning procedure by
``test_xplane_freeze_protocol.py`` / ``test_xplane_scenery_reload.py``, so what
is left — and what this file checks — is the seam between them:

* the state is re-read at write time, not taken from a caller's preview (D7);
* the precondition is enforced *before* anything is written (D8);
* the target handed to :meth:`set_position` is the one
  :func:`core.pushback.pushback_target` computes from that state;
* ``ias_kt`` and ``vertical_speed_fpm`` are both **0.0**, passed explicitly —
  ``None`` would preserve the aircraft's current speed, and a pushback that
  leaves the aeroplane rolling is not a pushback.

Nothing here opens a socket: :class:`_DelegateRecordingAdapter` replaces
``get_aircraft_state`` and ``set_position`` with a ledger.
"""

from __future__ import annotations

from typing import Any

import pytest

from adapters.xplane.xplane_adapter import XPlaneSimAdapter
from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.models import AircraftState, GeoPosition
from core.pushback import PushbackNotOnGround, PushbackRequest, pushback_target
from core.sim_adapter import Capabilities, CapabilityNotSupported

#: A parked aircraft at LEMD, nose on 123°. Grounded, stationary — the state a
#: pushback is actually issued from.
PARKED = AircraftState(
    latitude=40.4936,
    longitude=-3.5668,
    altitude_ft=1998.0,
    heading_deg=123.0,
    ias_kt=0.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=True,
)

#: The same aircraft, airborne — nothing else changed, so a test that uses it
#: isolates the precondition and not some second difference.
AIRBORNE = PARKED.model_copy(update={"on_ground": False, "ias_kt": 120.0, "altitude_ft": 3000.0})


class _DelegateRecordingAdapter(XPlaneSimAdapter):
    """An adapter whose reads and teleports are a ledger instead of a wire.

    Only the two methods ``pushback()`` calls are replaced. Everything between
    them — the capability check, the precondition, the geometry call — is the
    real adapter's code running unmodified.
    """

    def __init__(self, state: AircraftState = PARKED) -> None:
        super().__init__()
        self.state = state
        self.state_reads = 0
        self.positions: list[tuple[GeoPosition, float, dict[str, Any]]] = []

    async def get_aircraft_state(self) -> AircraftState:
        self.state_reads += 1
        return self.state

    async def set_position(
        self,
        position: GeoPosition,
        heading_deg: float,
        *,
        ias_kt: float | None = None,
        vertical_speed_fpm: float | None = None,
    ) -> None:
        self.positions.append(
            (position, heading_deg, {"ias_kt": ias_kt, "vertical_speed_fpm": vertical_speed_fpm})
        )
        # A real teleport moves the aircraft, and the next pushback must read
        # the *new* state — modelling that is what makes the chaining test mean
        # something. Speed is forced to zero the way the write commands it.
        self.state = self.state.model_copy(
            update={
                "latitude": position.latitude,
                "longitude": position.longitude,
                "heading_deg": heading_deg,
                "ias_kt": 0.0,
                "vertical_speed_fpm": 0.0,
            }
        )


def _metres_between(start: GeoPosition, end: GeoPosition) -> tuple[float, float]:
    distance_nm, bearing_deg = distance_and_bearing(start, end)
    return distance_nm * METRES_PER_NAUTICAL_MILE, bearing_deg


def _position_of(state: AircraftState) -> GeoPosition:
    return GeoPosition(
        latitude=state.latitude, longitude=state.longitude, altitude_ft=state.altitude_ft
    )


async def test_pushback_teleports_to_the_computed_target() -> None:
    """The delegation, exactly as §5.1 writes it: one read, one teleport.

    The target is asserted against :func:`core.pushback.pushback_target` rather
    than against a hand-computed coordinate — the design's D7 point is that the
    adapter and the preview route call the *same* pure function, so what must
    be pinned is that identity, not a second copy of the geometry.
    """
    adapter = _DelegateRecordingAdapter()
    request = PushbackRequest(direction="straight", distance_m=20.0)
    expected = pushback_target(PARKED, request)

    await adapter.pushback(request)

    assert adapter.state_reads == 1, "the state is re-read at write time (D7), once"
    assert len(adapter.positions) == 1
    position, heading_deg, speeds = adapter.positions[0]
    assert position == expected.position
    assert heading_deg == pytest.approx(expected.heading_deg)
    assert speeds == {"ias_kt": 0.0, "vertical_speed_fpm": 0.0}


async def test_a_straight_push_ends_up_behind_the_aircraft() -> None:
    """The hand-checkable half: 20 m along the reciprocal of the heading, nose unturned."""
    adapter = _DelegateRecordingAdapter()
    home = _position_of(PARKED)

    await adapter.pushback(PushbackRequest(direction="straight", distance_m=20.0))

    distance_m, bearing_deg = _metres_between(home, _position_of(adapter.state))
    assert distance_m == pytest.approx(20.0, abs=0.1)
    assert bearing_deg == pytest.approx((PARKED.heading_deg + 180.0) % 360.0, abs=0.5)
    assert adapter.state.heading_deg == pytest.approx(PARKED.heading_deg)


@pytest.mark.parametrize(("direction", "expected_delta_deg"), [("right", 45.0), ("left", -45.0)])
async def test_an_arc_rotates_the_nose_in_the_requested_direction(
    direction: str, expected_delta_deg: float
) -> None:
    """D5's sign convention carried through the adapter, not just through ``core``.

    Getting it backwards is a confusing, non-dangerous bug the design flags
    explicitly (§10.2) — precisely the kind that survives a live run because
    the aircraft does move, just the wrong way.
    """
    adapter = _DelegateRecordingAdapter()

    await adapter.pushback(
        PushbackRequest(direction=direction, distance_m=20.0, angle_deg=45.0)  # type: ignore[arg-type]
    )

    _, heading_deg, _ = adapter.positions[0]
    assert heading_deg == pytest.approx((PARKED.heading_deg + expected_delta_deg) % 360.0)


async def test_pushback_refuses_an_airborne_aircraft_without_writing() -> None:
    """D8: a precondition, not a capability — and nothing is written.

    The order matters as much as the exception. ``require_on_ground`` runs
    before the geometry and before the teleport, so a refusal cannot leave a
    half-applied manoeuvre or a frozen flight model behind.
    """
    adapter = _DelegateRecordingAdapter(state=AIRBORNE)

    with pytest.raises(PushbackNotOnGround):
        await adapter.pushback(PushbackRequest(direction="straight", distance_m=20.0))

    assert adapter.positions == []
    assert adapter.state == AIRBORNE


async def test_two_pushes_chain_from_the_state_the_first_one_left() -> None:
    """Pushback is relative, so the second call re-reads rather than reusing a preview (D7)."""
    adapter = _DelegateRecordingAdapter()
    home = _position_of(PARKED)
    request = PushbackRequest(direction="straight", distance_m=20.0)

    await adapter.pushback(request)
    after_one = _position_of(adapter.state)
    await adapter.pushback(request)
    after_two = _position_of(adapter.state)

    assert adapter.state_reads == 2
    assert _metres_between(home, after_one)[0] == pytest.approx(20.0, abs=0.1)
    assert _metres_between(home, after_two)[0] == pytest.approx(40.0, abs=0.2)


async def test_pushback_refuses_without_the_capability() -> None:
    """The refusal half of the flag, on the X-Plane adapter specifically.

    The contract suite's own version of this can only use a restricted
    ``FakeSimAdapter`` subclass, so nothing there proves *this* adapter checks
    its flag before reading or writing anything.
    """

    class _NoPushbackAdapter(_DelegateRecordingAdapter):
        @property
        def capabilities(self) -> Capabilities:
            return super().capabilities.model_copy(update={"can_pushback": False})

    adapter = _NoPushbackAdapter()
    with pytest.raises(CapabilityNotSupported, match="can_pushback"):
        await adapter.pushback(PushbackRequest(direction="straight", distance_m=20.0))

    assert adapter.state_reads == 0
    assert adapter.positions == []
