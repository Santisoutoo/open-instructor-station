"""``core.camera.geometry`` — resolving an aircraft-relative camera offset, and back.

Per ``docs/designs/camera-manager.md`` §8.1. Every reference value here comes
from the design itself (its §3 worked example and the §8.1 list), so the tests
pin the *specification*, not whatever the implementation happens to compute.

Two conventions are deliberately mixed (D5) and both are asserted separately,
because either could defensibly have gone the other way: ``look_offset_deg`` is
relative to the aircraft's heading, ``pitch_deg`` is world-frame and passes
through untouched.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from core.camera.geometry import derive_camera_offset, resolve_camera_pose
from core.camera.models import CameraOffset, CameraPose
from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.models import AircraftState, GeoPosition

#: The aircraft every case is resolved against unless it needs another heading.
#: Mid-latitude and level, so the geometry reads by eye.
EAST_BOUND = AircraftState(
    latitude=40.0,
    longitude=-3.0,
    altitude_ft=3000.0,
    heading_deg=90.0,
    ias_kt=120.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
)

#: Metres of position error this module is willing to call "the same point".
#: A millimetre, per the design's own §8.1 claim. The residual actually
#: measured across latitudes 0-75 deg and the full ±500 m envelope is ~12 nm, so
#: this tolerance is the *specification*, not a fit to the implementation —
#: and it is five orders of magnitude away from the 145 mm the same grid gives
#: without ``derive_camera_offset``'s refinement pass.
TOLERANCE_M = 0.001

#: Degrees of angular error, per §8.1.
TOLERANCE_DEG = 0.01

#: 20 m expressed in feet — the worked example's altitude offset.
TWENTY_METRES_FT = 20.0 / 0.3048


def _state(heading_deg: float) -> AircraftState:
    return EAST_BOUND.model_copy(update={"heading_deg": heading_deg})


class TestResolveCameraPose:
    """The design's own worked examples, one test each."""

    def test_the_worked_example_from_the_design(self) -> None:
        """Heading 090°, 50 m ahead, 20 m up, looking straight ahead (§3).

        The resolved point must sit 50 m away on a true bearing of 090°, one
        aircraft-altitude plus ``20 / 0.3048`` ft high, with the camera looking
        on exactly 90.0°.
        """
        pose = resolve_camera_pose(
            EAST_BOUND,
            CameraOffset(
                forward_m=50.0, right_m=0.0, up_m=20.0, look_offset_deg=0.0, pitch_deg=0.0
            ),
        )

        distance_nm, bearing_deg = distance_and_bearing(
            GeoPosition(latitude=EAST_BOUND.latitude, longitude=EAST_BOUND.longitude),
            pose.position,
        )
        assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(50.0, abs=TOLERANCE_M)
        assert bearing_deg == pytest.approx(90.0, abs=TOLERANCE_DEG)
        assert pose.position.altitude_ft == pytest.approx(
            EAST_BOUND.altitude_ft + TWENTY_METRES_FT, abs=0.001
        )
        assert pose.heading_deg == 90.0

    def test_right_is_east_of_a_northbound_aircraft(self) -> None:
        """Heading 000°, ``right_m=30`` -> 30 m due east (§8.1)."""
        state = _state(0.0)
        pose = resolve_camera_pose(
            state,
            CameraOffset(forward_m=0.0, right_m=30.0, up_m=0.0, look_offset_deg=0.0, pitch_deg=0.0),
        )

        distance_nm, bearing_deg = distance_and_bearing(
            GeoPosition(latitude=state.latitude, longitude=state.longitude), pose.position
        )
        assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(30.0, abs=TOLERANCE_M)
        assert bearing_deg == pytest.approx(90.0, abs=TOLERANCE_DEG)

    def test_negative_forward_is_behind_the_aircraft(self) -> None:
        """``forward_m=-40`` on heading 090° puts the camera 40 m due west."""
        pose = resolve_camera_pose(
            EAST_BOUND,
            CameraOffset(
                forward_m=-40.0, right_m=0.0, up_m=0.0, look_offset_deg=0.0, pitch_deg=0.0
            ),
        )

        distance_nm, bearing_deg = distance_and_bearing(
            GeoPosition(latitude=EAST_BOUND.latitude, longitude=EAST_BOUND.longitude),
            pose.position,
        )
        assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(40.0, abs=TOLERANCE_M)
        assert bearing_deg == pytest.approx(270.0, abs=TOLERANCE_DEG)

    def test_look_offset_wraps_through_north(self) -> None:
        """Heading 270° + 90° of look offset is exactly 0.0, not 360.0 (§8.1)."""
        pose = resolve_camera_pose(
            _state(270.0),
            CameraOffset(forward_m=0.0, right_m=0.0, up_m=0.0, look_offset_deg=90.0, pitch_deg=0.0),
        )
        assert pose.heading_deg == 0.0

    def test_look_offset_wraps_the_other_way(self) -> None:
        """Heading 010 deg minus 30 deg of look offset folds to 340 deg, never to -20 deg."""
        pose = resolve_camera_pose(
            _state(10.0),
            CameraOffset(
                forward_m=0.0, right_m=0.0, up_m=0.0, look_offset_deg=-30.0, pitch_deg=0.0
            ),
        )
        assert pose.heading_deg == pytest.approx(340.0)

    def test_pitch_is_world_frame_and_untouched_by_the_aircraft_attitude(self) -> None:
        """D5: the aircraft's own pitch never enters the camera's.

        Two identical offsets, one on a level aircraft and one on an aircraft
        in a 15° climb, must resolve to the same camera pitch — that is the
        whole content of "world frame".
        """
        offset = CameraOffset(
            forward_m=0.0, right_m=0.0, up_m=0.0, look_offset_deg=0.0, pitch_deg=-12.0
        )
        climbing = EAST_BOUND.model_copy(update={"pitch_deg": 15.0})

        assert resolve_camera_pose(EAST_BOUND, offset).pitch_deg == -12.0
        assert resolve_camera_pose(climbing, offset).pitch_deg == -12.0

    def test_zoom_passes_through(self) -> None:
        offset = CameraOffset(
            forward_m=0.0,
            right_m=0.0,
            up_m=0.0,
            look_offset_deg=0.0,
            pitch_deg=0.0,
            zoom_ratio=2.5,
        )
        assert resolve_camera_pose(EAST_BOUND, offset).zoom_ratio == 2.5

    def test_a_diagonal_offset_lands_at_the_expected_distance(self) -> None:
        """50 m ahead and 50 m right is 70.71 m out on a bearing of 135° from 090°."""
        pose = resolve_camera_pose(
            EAST_BOUND,
            CameraOffset(
                forward_m=50.0, right_m=50.0, up_m=0.0, look_offset_deg=0.0, pitch_deg=0.0
            ),
        )

        distance_nm, bearing_deg = distance_and_bearing(
            GeoPosition(latitude=EAST_BOUND.latitude, longitude=EAST_BOUND.longitude),
            pose.position,
        )
        assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(
            50.0 * math.sqrt(2.0), abs=TOLERANCE_M
        )
        assert bearing_deg == pytest.approx(135.0, abs=TOLERANCE_DEG)


class TestDeriveCameraOffset:
    """The inverse, and the round trip the design's docstring claims (§6/§8.1)."""

    @pytest.mark.parametrize(
        "offset",
        [
            CameraOffset(forward_m=0.0, right_m=0.0, up_m=0.0, look_offset_deg=0.0, pitch_deg=0.0),
            CameraOffset(
                forward_m=50.0, right_m=0.0, up_m=20.0, look_offset_deg=0.0, pitch_deg=0.0
            ),
            CameraOffset(
                forward_m=-30.0, right_m=15.0, up_m=-5.0, look_offset_deg=45.0, pitch_deg=-12.0
            ),
            # Just inside the model's +/-500 m envelope rather than exactly on
            # it. At the exact corner the recovered value carries nanometres of
            # float noise, which a hard ``le=500.0`` rejects or accepts purely
            # on which side of the bound that noise happens to land — a coin
            # toss to assert either way, and nothing about the geometry.
            CameraOffset(
                forward_m=499.0,
                right_m=499.0,
                up_m=499.0,
                look_offset_deg=179.0,
                pitch_deg=90.0,
                zoom_ratio=10.0,
            ),
            CameraOffset(
                forward_m=-499.0,
                right_m=-499.0,
                up_m=-499.0,
                look_offset_deg=-179.0,
                pitch_deg=-90.0,
                zoom_ratio=0.25,
            ),
            CameraOffset(
                forward_m=0.0, right_m=-250.0, up_m=0.0, look_offset_deg=-90.0, pitch_deg=30.0
            ),
        ],
    )
    @pytest.mark.parametrize("heading_deg", [0.0, 90.0, 187.5, 359.0])
    def test_round_trips_a_resolved_pose(self, offset: CameraOffset, heading_deg: float) -> None:
        """``derive(resolve(offset))`` reproduces ``offset`` within 1 mm / 0.01° (§8.1).

        Pinned as a test rather than left asserted in ``geometry.py``'s prose:
        the recovery is flat-plane trigonometry over a two-hop geodesic
        composition, and the claim that the residual is negligible at ±500 m is
        exactly the kind of claim that rots silently.
        """
        state = _state(heading_deg)
        recovered = derive_camera_offset(state, resolve_camera_pose(state, offset))

        assert recovered.forward_m == pytest.approx(offset.forward_m, abs=TOLERANCE_M)
        assert recovered.right_m == pytest.approx(offset.right_m, abs=TOLERANCE_M)
        assert recovered.up_m == pytest.approx(offset.up_m, abs=TOLERANCE_M)
        assert recovered.look_offset_deg == pytest.approx(offset.look_offset_deg, abs=TOLERANCE_DEG)
        assert recovered.pitch_deg == pytest.approx(offset.pitch_deg, abs=TOLERANCE_DEG)
        assert recovered.zoom_ratio == pytest.approx(offset.zoom_ratio)

    def test_look_offset_of_180_stays_inside_the_models_bounds(self) -> None:
        """Looking straight back folds to -180.0, which the model allows; +180 would too.

        The fold has to pick one, and picking neither — leaving 180.0 as, say,
        an unfolded 540.0 — is the failure this guards against.
        """
        state = _state(90.0)
        pose = CameraPose(
            position=GeoPosition(
                latitude=state.latitude,
                longitude=state.longitude,
                altitude_ft=state.altitude_ft,
            ),
            heading_deg=270.0,
            pitch_deg=0.0,
            zoom_ratio=1.0,
        )
        assert abs(derive_camera_offset(state, pose).look_offset_deg) == 180.0

    def test_altitude_difference_becomes_up_metres(self) -> None:
        state = _state(90.0)
        pose = CameraPose(
            position=GeoPosition(
                latitude=state.latitude,
                longitude=state.longitude,
                altitude_ft=state.altitude_ft + TWENTY_METRES_FT,
            ),
            heading_deg=90.0,
            pitch_deg=0.0,
            zoom_ratio=1.0,
        )
        assert derive_camera_offset(state, pose).up_m == pytest.approx(20.0, abs=TOLERANCE_M)

    def test_a_pose_beyond_the_models_envelope_is_refused(self) -> None:
        """A camera 2 km out is not an offset this manager can express.

        ``CameraOffset``'s ±500 m bound is the contract; silently clamping the
        pose to it would hand the instructor a framing they never chose.
        """
        state = _state(90.0)
        far_away = resolve_camera_pose(
            state,
            CameraOffset(
                forward_m=500.0, right_m=0.0, up_m=0.0, look_offset_deg=0.0, pitch_deg=0.0
            ),
        )
        four_times_out = CameraPose(
            position=GeoPosition(
                latitude=far_away.position.latitude,
                longitude=-3.0 + 4.0 * (far_away.position.longitude + 3.0),
                altitude_ft=far_away.position.altitude_ft,
            ),
            heading_deg=far_away.heading_deg,
            pitch_deg=far_away.pitch_deg,
            zoom_ratio=far_away.zoom_ratio,
        )

        with pytest.raises(ValidationError):
            derive_camera_offset(state, four_times_out)
