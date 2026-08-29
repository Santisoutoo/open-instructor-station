"""Numeric tests for ``core.pushback`` — the geometry, the models, the
precondition — checked against the design's own worked reference values
(``docs/designs/pushback-manager.md`` §3, §6, §8.1), never against the
implementation.

The worked example (D5): aircraft heading 090 deg (east), ``direction="right"``,
``distance_m=30``, ``angle_deg=90`` -> heading 180.0 deg exactly (090 + 90, no
trig needed), and the chord is a circular-arc identity:
``radius_m = 30 / (pi/2) ~= 19.10 m``,
``chord_m = 2 * radius_m * sin(45 deg) ~= 27.01 m``,
at true bearing ``back_bearing (270) + angle_deg / 2 (45) = 315 deg`` from the
start. Every number here is computed independently with :mod:`math`, not
imported from ``core.pushback``.
"""

import math

import pytest
from pydantic import ValidationError

from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.models import AircraftState, GeoPosition
from core.pushback import (
    PUSHBACK_MAX_ANGLE_DEG,
    PUSHBACK_MAX_DISTANCE_M,
    PUSHBACK_PATH_PREVIEW_POINTS,
    PushbackNotOnGround,
    PushbackRequest,
    pushback_target,
    require_on_ground,
)

#: The aeroplane the instructor starts from: parked on a stand, heading east.
#: Chosen at 090 deg specifically so the heading arithmetic in the worked
#: example needs no modulo wraparound to check by hand.
PARKED_EAST = AircraftState(
    latitude=40.0,
    longitude=-3.0,
    altitude_ft=2000.0,
    heading_deg=90.0,
    ias_kt=0.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=True,
)

AIRBORNE_EAST = PARKED_EAST.model_copy(update={"on_ground": False, "ias_kt": 250.0})

ORIGIN = GeoPosition(
    latitude=PARKED_EAST.latitude,
    longitude=PARKED_EAST.longitude,
    altitude_ft=PARKED_EAST.altitude_ft,
)

#: Tolerances the design states: 1 mm for position/chord, 0.01 deg for bearing.
POSITION_TOLERANCE_M = 0.001
BEARING_TOLERANCE_DEG = 0.01


def _distance_m(a: GeoPosition, b: GeoPosition) -> float:
    distance_nm, _ = distance_and_bearing(a, b)
    return distance_nm * METRES_PER_NAUTICAL_MILE


# --------------------------------------------------------------------------
# PushbackRequest validation (§3, §8.1)
# --------------------------------------------------------------------------


def test_straight_with_nonzero_angle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PushbackRequest(direction="straight", distance_m=20.0, angle_deg=5.0)


def test_left_or_right_with_zero_angle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PushbackRequest(direction="left", distance_m=20.0, angle_deg=0.0)


def test_right_with_a_positive_angle_is_valid() -> None:
    request = PushbackRequest(direction="right", distance_m=20.0, angle_deg=45.0)
    assert request.angle_deg == 45.0


def test_straight_defaults_angle_to_zero() -> None:
    request = PushbackRequest(direction="straight", distance_m=20.0)
    assert request.angle_deg == 0.0


def test_distance_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        PushbackRequest(direction="straight", distance_m=0.0)


def test_distance_beyond_the_max_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PushbackRequest(direction="straight", distance_m=PUSHBACK_MAX_DISTANCE_M + 1.0)


def test_angle_beyond_the_max_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PushbackRequest(direction="right", distance_m=20.0, angle_deg=PUSHBACK_MAX_ANGLE_DEG + 1.0)


def test_request_is_frozen_and_forbids_extra_fields() -> None:
    request = PushbackRequest(direction="straight", distance_m=20.0)
    with pytest.raises(ValidationError):
        request.distance_m = 30.0
    with pytest.raises(ValidationError):
        PushbackRequest.model_validate(
            {"direction": "straight", "distance_m": 20.0, "extra_field": 1}
        )


# --------------------------------------------------------------------------
# require_on_ground (D8, §8.1)
# --------------------------------------------------------------------------


def test_require_on_ground_raises_when_airborne() -> None:
    with pytest.raises(PushbackNotOnGround):
        require_on_ground(AIRBORNE_EAST)


def test_require_on_ground_does_not_raise_on_the_ground() -> None:
    require_on_ground(PARKED_EAST)  # must not raise


# --------------------------------------------------------------------------
# Straight push (angle 0)
# --------------------------------------------------------------------------


def test_straight_push_travels_the_reciprocal_heading() -> None:
    """Heading 090, distance_m=20 -> 20 m at the back bearing (270 deg), heading unchanged.

    Design §8.1's straight case: ``distance_and_bearing`` from origin to
    ``target.position`` is ``(20 / 1852 NM, 270 deg)`` within 1 mm.
    """
    request = PushbackRequest(direction="straight", distance_m=20.0)
    target = pushback_target(PARKED_EAST, request)

    distance_nm, bearing_deg = distance_and_bearing(ORIGIN, target.position)
    assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(20.0, abs=POSITION_TOLERANCE_M)
    assert bearing_deg == pytest.approx(270.0, abs=BEARING_TOLERANCE_DEG)
    assert target.heading_deg == pytest.approx(90.0, abs=1e-9)


def test_straight_push_path_preview_is_collinear() -> None:
    """Every intermediate point of a straight push lies on the single back-bearing radial."""
    request = PushbackRequest(direction="straight", distance_m=20.0)
    target = pushback_target(PARKED_EAST, request)

    for point in target.path_preview[1:]:
        _, bearing_deg = distance_and_bearing(ORIGIN, point)
        assert bearing_deg == pytest.approx(270.0, abs=BEARING_TOLERANCE_DEG)


# --------------------------------------------------------------------------
# Right arc — the worked example (D5, §3, §8.1)
# --------------------------------------------------------------------------


def test_right_arc_worked_example_heading() -> None:
    """The hand-checkable half: 090 + 90 = 180, no trig needed."""
    request = PushbackRequest(direction="right", distance_m=30.0, angle_deg=90.0)
    target = pushback_target(PARKED_EAST, request)
    assert target.heading_deg == pytest.approx(180.0, abs=1e-9)


def test_right_arc_worked_example_chord() -> None:
    """Chord distance and bearing, computed independently via ``math``.

    ``radius_m = 30 / (pi/2)``, ``chord_m = 2 * radius_m * sin(pi/4) ~= 27.0095 m``,
    at true bearing ``315 deg`` (back bearing 270 + angle/2 = 45) from the origin.
    """
    request = PushbackRequest(direction="right", distance_m=30.0, angle_deg=90.0)
    target = pushback_target(PARKED_EAST, request)

    radius_m = 30.0 / (math.pi / 2.0)
    expected_chord_m = 2.0 * radius_m * math.sin(math.radians(45.0))
    assert expected_chord_m == pytest.approx(27.0095, abs=0.001)

    distance_nm, bearing_deg = distance_and_bearing(ORIGIN, target.position)
    assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(
        expected_chord_m, abs=POSITION_TOLERANCE_M
    )
    assert bearing_deg == pytest.approx(315.0, abs=BEARING_TOLERANCE_DEG)


# --------------------------------------------------------------------------
# Left arc — same inputs, opposite sign (D5)
# --------------------------------------------------------------------------


def test_left_arc_worked_example_heading() -> None:
    """090 - 90 = 0 -- counter-clockwise, the mirror of the right-arc case."""
    request = PushbackRequest(direction="left", distance_m=30.0, angle_deg=90.0)
    target = pushback_target(PARKED_EAST, request)
    assert target.heading_deg == pytest.approx(0.0, abs=1e-9)


def test_left_arc_worked_example_chord_bearing() -> None:
    """Chord bearing 270 - 45 = 225 deg, magnitude identical to the right-arc case."""
    request = PushbackRequest(direction="left", distance_m=30.0, angle_deg=90.0)
    target = pushback_target(PARKED_EAST, request)

    radius_m = 30.0 / (math.pi / 2.0)
    expected_chord_m = 2.0 * radius_m * math.sin(math.radians(45.0))

    distance_nm, bearing_deg = distance_and_bearing(ORIGIN, target.position)
    assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(
        expected_chord_m, abs=POSITION_TOLERANCE_M
    )
    assert bearing_deg == pytest.approx(225.0, abs=BEARING_TOLERANCE_DEG)


def test_nose_convention_is_pinned_right_is_clockwise() -> None:
    """D5 pinned exactly: 'right' rotates the final heading CLOCKWISE from the
    current one. Same distance/angle magnitude, opposite direction, must
    produce headings symmetric about the starting heading (090)."""
    right_request = PushbackRequest(direction="right", distance_m=30.0, angle_deg=90.0)
    left_request = PushbackRequest(direction="left", distance_m=30.0, angle_deg=90.0)
    right = pushback_target(PARKED_EAST, right_request)
    left = pushback_target(PARKED_EAST, left_request)

    assert right.heading_deg == pytest.approx((PARKED_EAST.heading_deg + 90.0) % 360.0, abs=1e-9)
    assert left.heading_deg == pytest.approx((PARKED_EAST.heading_deg - 90.0) % 360.0, abs=1e-9)


# --------------------------------------------------------------------------
# 180 deg U-turn (§8.1)
# --------------------------------------------------------------------------


def test_u_turn_heading_wraps_by_the_full_180() -> None:
    request = PushbackRequest(direction="right", distance_m=40.0, angle_deg=180.0)
    target = pushback_target(PARKED_EAST, request)
    assert target.heading_deg == pytest.approx((PARKED_EAST.heading_deg + 180.0) % 360.0, abs=1e-9)


def test_u_turn_radius_is_distance_over_pi() -> None:
    """A 180 deg sweep's own identity: ``radius_m == distance_m / pi`` exactly,
    so the chord (a full semicircle) is the diameter, ``2 * radius_m``."""
    distance_m = 40.0
    request = PushbackRequest(direction="right", distance_m=distance_m, angle_deg=180.0)
    target = pushback_target(PARKED_EAST, request)

    radius_m = distance_m / math.pi
    expected_chord_m = 2.0 * radius_m  # diameter: sin(90 deg) == 1

    distance_nm, _ = distance_and_bearing(ORIGIN, target.position)
    assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(
        expected_chord_m, abs=POSITION_TOLERANCE_M
    )


# --------------------------------------------------------------------------
# Path preview shape (§8.1)
# --------------------------------------------------------------------------


def test_path_preview_starts_at_the_origin() -> None:
    request = PushbackRequest(direction="right", distance_m=30.0, angle_deg=90.0)
    target = pushback_target(PARKED_EAST, request)
    first = target.path_preview[0]
    assert _distance_m(ORIGIN, first) == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)


def test_path_preview_ends_exactly_at_the_target() -> None:
    request = PushbackRequest(direction="right", distance_m=30.0, angle_deg=90.0)
    target = pushback_target(PARKED_EAST, request)
    assert target.path_preview[-1] == target.position


def test_path_preview_has_the_documented_point_count() -> None:
    request = PushbackRequest(direction="straight", distance_m=20.0)
    target = pushback_target(PARKED_EAST, request)
    assert len(target.path_preview) == PUSHBACK_PATH_PREVIEW_POINTS + 1


def test_path_preview_point_count_honours_a_custom_preview_points() -> None:
    request = PushbackRequest(direction="right", distance_m=30.0, angle_deg=90.0)
    target = pushback_target(PARKED_EAST, request, preview_points=3)
    assert len(target.path_preview) == 3 + 1


def test_arc_path_preview_points_lie_on_the_same_circle() -> None:
    """Every intermediate point of an arc is equidistant from the arc's centre.

    The centre sits ``radius_m`` from the origin, perpendicular to the initial
    tangent (the current heading), on the side the arc curves toward — for a
    right turn from a back-bearing start, that is ``back_bearing + 90``
    (a right turn curves toward the nose's right, i.e. the observer's right
    when standing at the origin facing the back bearing).
    """
    distance_m = 30.0
    angle_deg = 90.0
    request = PushbackRequest(direction="right", distance_m=distance_m, angle_deg=angle_deg)
    target = pushback_target(PARKED_EAST, request)

    radius_m = distance_m / math.radians(angle_deg)
    back_bearing_deg = (PARKED_EAST.heading_deg + 180.0) % 360.0
    # The centre of a right turn lies 90 deg clockwise of the back bearing.
    centre_bearing_deg = (back_bearing_deg + 90.0) % 360.0
    centre = point_at_distance_and_bearing(
        ORIGIN, radius_m / METRES_PER_NAUTICAL_MILE, centre_bearing_deg
    )

    radii_m = [_distance_m(centre, point) for point in target.path_preview]
    for measured in radii_m:
        assert measured == pytest.approx(radius_m, abs=POSITION_TOLERANCE_M)


def test_straight_path_preview_points_are_collinear_with_the_target() -> None:
    request = PushbackRequest(direction="straight", distance_m=20.0)
    target = pushback_target(PARKED_EAST, request)

    bearings = [distance_and_bearing(ORIGIN, point)[1] for point in target.path_preview[1:]]
    for bearing_deg in bearings:
        assert bearing_deg == pytest.approx(270.0, abs=BEARING_TOLERANCE_DEG)


# --------------------------------------------------------------------------
# Heading normalisation
# --------------------------------------------------------------------------


def test_heading_wraps_past_360() -> None:
    """A right push from a heading close to 360 must wrap into [0, 360)."""
    near_north = PARKED_EAST.model_copy(update={"heading_deg": 350.0})
    request = PushbackRequest(direction="right", distance_m=20.0, angle_deg=30.0)
    target = pushback_target(near_north, request)
    assert target.heading_deg == pytest.approx(20.0, abs=1e-9)
    assert 0.0 <= target.heading_deg <= 360.0
