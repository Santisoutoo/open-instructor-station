"""Numeric tests for the geodesy primitives and the placements built on them.

The numbers here are checked against published values, not against the
implementation: 1 NM = 1852 m exactly, 1 NM = 1852 / 0.3048 ft, and a 3°
glidepath is 318.44 ft per nautical mile.
"""

import math
from typing import get_args

import pytest

from core.geodesy import (
    DEFAULT_PATTERN_ALTITUDE_AGL_FT,
    FEET_PER_NAUTICAL_MILE,
    FINAL_DISTANCES_NM,
    METRES_PER_NAUTICAL_MILE,
    PATTERN_PLACEMENTS,
    RUNWAY_PLACEMENTS,
    SHORT_FINAL_DISTANCE_NM,
    FinalPlacement,
    PatternLeg,
    PatternPlacement,
    coordinate_placement,
    distance_and_bearing,
    final_approach_point,
    final_placement,
    glideslope_altitude_ft,
    pattern_placement,
    point_at_distance_and_bearing,
    resolve_runway_placement,
    traffic_pattern_point,
    waypoint_placement,
)
from core.models import GeoPosition
from tests.conftest import NORTH_RUNWAY, SAMPLE_RUNWAY

MADRID = GeoPosition(latitude=40.4168, longitude=-3.7038, altitude_ft=2000.0)

#: A 3° glidepath climbs tan(3°) * 6076.115486 = 318.4357 ft every nautical
#: mile. Every altitude assertion below is that number times a distance.
FT_PER_NM_ON_A_THREE_DEGREE_PATH = 318.4357


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------


def test_nautical_mile_constants() -> None:
    assert METRES_PER_NAUTICAL_MILE == 1852.0
    assert pytest.approx(6076.115486, abs=1e-5) == FEET_PER_NAUTICAL_MILE


# --------------------------------------------------------------------------
# Glideslope
# --------------------------------------------------------------------------


def test_three_degree_glideslope_is_318_ft_per_nm() -> None:
    """The standard rule of thumb: ~318 ft per NM on a 3° path."""
    assert glideslope_altitude_ft(0.0, 1.0) == pytest.approx(318.44, abs=0.01)


def test_ten_nm_final_on_a_three_degree_glideslope() -> None:
    """tan(3°) * 10 NM * 6076.115486 ft/NM = 3184.36 ft above the threshold."""
    assert glideslope_altitude_ft(0.0, 10.0) == pytest.approx(3184.36, abs=0.01)


def test_glideslope_adds_to_threshold_elevation() -> None:
    assert glideslope_altitude_ft(2000.0, 10.0) == pytest.approx(2000.0 + 3184.36, abs=0.01)


def test_glideslope_at_the_threshold_is_the_threshold_elevation() -> None:
    assert glideslope_altitude_ft(1234.0, 0.0) == pytest.approx(1234.0)


def test_steeper_glideslope_is_higher() -> None:
    assert glideslope_altitude_ft(0.0, 5.0, 5.5) > glideslope_altitude_ft(0.0, 5.0, 3.0)


# --------------------------------------------------------------------------
# Direct / inverse geodesic problems
# --------------------------------------------------------------------------


def test_one_nm_north_is_about_one_arcminute_of_latitude() -> None:
    north = point_at_distance_and_bearing(MADRID, 1.0, 0.0)
    assert north.latitude - MADRID.latitude == pytest.approx(1.0 / 60.0, abs=2e-4)
    assert north.longitude == pytest.approx(MADRID.longitude, abs=1e-9)


def test_direct_carries_the_origin_altitude() -> None:
    assert point_at_distance_and_bearing(MADRID, 25.0, 137.0).altitude_ft == MADRID.altitude_ft


@pytest.mark.parametrize("bearing", [0.0, 45.0, 90.0, 179.0, 233.5, 359.9])
@pytest.mark.parametrize("distance_nm", [0.5, 10.0, 250.0])
def test_direct_inverse_round_trip(bearing: float, distance_nm: float) -> None:
    """Going out and measuring back must return the same distance and bearing."""
    destination = point_at_distance_and_bearing(MADRID, distance_nm, bearing)
    measured_nm, measured_bearing = distance_and_bearing(MADRID, destination)
    assert measured_nm == pytest.approx(distance_nm, abs=1e-6)
    assert measured_bearing == pytest.approx(bearing, abs=1e-6)


def test_a_negative_distance_travels_backwards_along_the_same_line() -> None:
    forward = point_at_distance_and_bearing(MADRID, 12.0, 75.0)
    backward = point_at_distance_and_bearing(MADRID, -12.0, 75.0)
    distance_nm, bearing = distance_and_bearing(MADRID, backward)
    assert distance_nm == pytest.approx(12.0, abs=1e-6)
    assert bearing == pytest.approx(255.0, abs=0.1)
    span_nm, _ = distance_and_bearing(backward, forward)
    assert span_nm == pytest.approx(24.0, abs=1e-6)


def test_inverse_bearing_is_normalised_to_0_360() -> None:
    west = point_at_distance_and_bearing(MADRID, 10.0, 270.0)
    _, bearing = distance_and_bearing(MADRID, west)
    assert 0.0 <= bearing < 360.0
    assert bearing == pytest.approx(270.0, abs=1e-6)


def test_distance_is_symmetric() -> None:
    other = point_at_distance_and_bearing(MADRID, 42.0, 61.0)
    there, _ = distance_and_bearing(MADRID, other)
    back, _ = distance_and_bearing(other, MADRID)
    assert there == pytest.approx(back, abs=1e-9)


# --------------------------------------------------------------------------
# Final approach point
# --------------------------------------------------------------------------


def test_final_approach_point_lies_on_the_extended_centreline() -> None:
    """10 NM out on a 320° runway is 10 NM from the threshold at bearing 140°."""
    point = final_approach_point(SAMPLE_RUNWAY, 10.0)
    distance_nm, bearing = distance_and_bearing(SAMPLE_RUNWAY.threshold, point)
    assert distance_nm == pytest.approx(10.0, abs=1e-6)
    assert bearing == pytest.approx(140.0, abs=1e-6)


def test_final_approach_point_is_on_the_glidepath() -> None:
    point = final_approach_point(SAMPLE_RUNWAY, 10.0)
    assert point.altitude_ft == pytest.approx(SAMPLE_RUNWAY.elevation_ft + 3184.36, abs=0.01)


def test_final_approach_point_honours_a_custom_glideslope() -> None:
    shallow = final_approach_point(SAMPLE_RUNWAY, 6.0, glideslope_deg=2.5)
    standard = final_approach_point(SAMPLE_RUNWAY, 6.0, glideslope_deg=3.0)
    assert shallow.altitude_ft < standard.altitude_ft
    assert shallow.latitude == pytest.approx(standard.latitude)
    assert shallow.longitude == pytest.approx(standard.longitude)


def test_final_approach_point_at_the_threshold_is_the_threshold() -> None:
    point = final_approach_point(SAMPLE_RUNWAY, 0.0)
    assert point.latitude == pytest.approx(SAMPLE_RUNWAY.threshold.latitude, abs=1e-9)
    assert point.longitude == pytest.approx(SAMPLE_RUNWAY.threshold.longitude, abs=1e-9)
    assert point.altitude_ft == pytest.approx(SAMPLE_RUNWAY.elevation_ft)


@pytest.mark.parametrize("distance_nm", [3.0, 5.0, 12.0, 25.0])
def test_final_approach_points_are_collinear_with_the_runway(distance_nm: float) -> None:
    point = final_approach_point(SAMPLE_RUNWAY, distance_nm)
    _, bearing_back = distance_and_bearing(point, SAMPLE_RUNWAY.threshold)
    # Flying from the final approach point to the threshold means flying the
    # runway heading (to within the geodesic's convergence over 25 NM).
    assert bearing_back == pytest.approx(SAMPLE_RUNWAY.true_bearing_deg, abs=0.3)


# --------------------------------------------------------------------------
# Traffic pattern
# --------------------------------------------------------------------------


ALL_LEGS: tuple[PatternLeg, ...] = ("upwind", "crosswind", "downwind", "base")
SIDE_LEGS: tuple[PatternLeg, ...] = ("downwind", "base", "crosswind")


def test_left_hand_pattern_headings() -> None:
    """On a runway 36, a left-hand pattern reads straight off the compass."""
    expected: dict[PatternLeg, float] = {
        "upwind": 0.0,
        "crosswind": 270.0,
        "downwind": 180.0,
        "base": 90.0,
    }
    for leg, heading in expected.items():
        _, actual = traffic_pattern_point(NORTH_RUNWAY, leg, 2000.0)
        assert actual == pytest.approx(heading, abs=1e-9), leg


def test_right_hand_pattern_mirrors_the_turns() -> None:
    expected: dict[PatternLeg, float] = {
        "upwind": 0.0,
        "crosswind": 90.0,
        "downwind": 180.0,
        "base": 270.0,
    }
    for leg, heading in expected.items():
        _, actual = traffic_pattern_point(NORTH_RUNWAY, leg, 2000.0, left_hand=False)
        assert actual == pytest.approx(heading, abs=1e-9), leg


def test_left_hand_pattern_lies_west_of_a_northbound_runway() -> None:
    for leg in SIDE_LEGS:
        position, _ = traffic_pattern_point(NORTH_RUNWAY, leg, 2000.0)
        assert position.longitude < NORTH_RUNWAY.threshold.longitude, leg


def test_right_hand_pattern_lies_east_of_a_northbound_runway() -> None:
    for leg in SIDE_LEGS:
        position, _ = traffic_pattern_point(NORTH_RUNWAY, leg, 2000.0, left_hand=False)
        assert position.longitude > NORTH_RUNWAY.threshold.longitude, leg


def test_upwind_is_on_the_centreline_beyond_the_departure_end() -> None:
    position, _ = traffic_pattern_point(NORTH_RUNWAY, "upwind", 2000.0, leg_distance_nm=1.5)
    assert position.longitude == pytest.approx(NORTH_RUNWAY.threshold.longitude, abs=1e-9)
    distance_nm, bearing = distance_and_bearing(NORTH_RUNWAY.threshold, position)
    expected_nm = NORTH_RUNWAY.length_m / METRES_PER_NAUTICAL_MILE + 1.5
    assert distance_nm == pytest.approx(expected_nm, abs=1e-6)
    assert bearing == pytest.approx(0.0, abs=1e-6)


def test_downwind_is_one_pattern_width_from_the_centreline() -> None:
    position, _ = traffic_pattern_point(NORTH_RUNWAY, "downwind", 2000.0, pattern_width_nm=0.8)
    # Project onto the centreline: the across-track component is the width.
    midfield = point_at_distance_and_bearing(
        NORTH_RUNWAY.threshold,
        NORTH_RUNWAY.length_m / METRES_PER_NAUTICAL_MILE / 2.0,
        NORTH_RUNWAY.true_bearing_deg,
    )
    offset_nm, offset_bearing = distance_and_bearing(midfield, position)
    assert offset_nm == pytest.approx(0.8, abs=1e-6)
    assert offset_bearing == pytest.approx(270.0, abs=0.1)


def test_base_is_before_the_threshold_on_the_approach_side() -> None:
    position, _ = traffic_pattern_point(NORTH_RUNWAY, "base", 2000.0, leg_distance_nm=2.0)
    assert position.latitude < NORTH_RUNWAY.threshold.latitude


def test_every_pattern_point_sits_at_pattern_altitude() -> None:
    for leg in ALL_LEGS:
        position, _ = traffic_pattern_point(NORTH_RUNWAY, leg, 2500.0)
        assert position.altitude_ft == pytest.approx(2500.0), leg


def test_pattern_geometry_rotates_with_the_runway() -> None:
    """A pattern on a 320° runway is the north pattern rotated by -40°."""
    _, heading = traffic_pattern_point(SAMPLE_RUNWAY, "downwind", 3000.0)
    assert heading == pytest.approx(math.fmod(320.0 + 180.0, 360.0), abs=1e-9)


# --------------------------------------------------------------------------
# The placement catalogue
# --------------------------------------------------------------------------


def _signed_delta(bearing_deg: float, reference_deg: float) -> float:
    """Angle from the reference to the bearing, folded into ``(-180, 180]``."""
    delta = (bearing_deg - reference_deg) % 360.0
    return delta - 360.0 if delta > 180.0 else delta


def _angular_gap(a_deg: float, b_deg: float) -> float:
    """Smallest absolute difference between two angles, wrap-safe, in degrees."""
    return abs(_signed_delta(a_deg, b_deg))


def test_signed_delta_helper_folds_across_north() -> None:
    """The test helper itself, so a wrap bug cannot silently pass a mirror test."""
    assert _signed_delta(10.0, 350.0) == pytest.approx(20.0)
    assert _signed_delta(350.0, 10.0) == pytest.approx(-20.0)
    assert _signed_delta(180.0, 0.0) == pytest.approx(180.0)
    assert _angular_gap(359.5, 0.5) == pytest.approx(1.0)


def test_final_distances_cover_every_named_final() -> None:
    assert set(FINAL_DISTANCES_NM) == set(get_args(FinalPlacement))
    assert dict(FINAL_DISTANCES_NM) == {
        "final_20nm": 20.0,
        "final_15nm": 15.0,
        "final_10nm": 10.0,
        "final_8nm": 8.0,
        "final_5nm": 5.0,
        "final_3nm": 3.0,
        "short_final": 1.0,
    }
    assert SHORT_FINAL_DISTANCE_NM == 1.0


def test_pattern_placements_cover_every_leg_on_both_sides() -> None:
    assert set(PATTERN_PLACEMENTS) == set(get_args(PatternPlacement))
    assert set(PATTERN_PLACEMENTS.values()) == {
        (leg, side)
        for leg in ("upwind", "crosswind", "downwind", "base")
        for side in ("left", "right")
    }


def test_runway_placements_is_the_whole_catalogue() -> None:
    assert list(RUNWAY_PLACEMENTS) == [*get_args(FinalPlacement), *get_args(PatternPlacement)]
    assert len(RUNWAY_PLACEMENTS) == 15
    assert len(set(RUNWAY_PLACEMENTS)) == 15


def test_every_placement_resolves_to_a_usable_answer() -> None:
    for name in RUNWAY_PLACEMENTS:
        placement = resolve_runway_placement(SAMPLE_RUNWAY, name)
        assert 0.0 <= placement.heading_deg < 360.0, name
        assert placement.label.startswith("LEMD 32L "), name
        assert placement.altitude_ft == placement.position.altitude_ft, name
        assert placement.altitude_ft > SAMPLE_RUNWAY.elevation_ft, name


# --------------------------------------------------------------------------
# Finals
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "distance_nm"),
    [
        ("final_20nm", 20.0),
        ("final_15nm", 15.0),
        ("final_10nm", 10.0),
        ("final_8nm", 8.0),
        ("final_5nm", 5.0),
        ("final_3nm", 3.0),
        ("short_final", 1.0),
    ],
)
def test_named_final_is_that_many_nm_out_on_the_glidepath(
    name: FinalPlacement, distance_nm: float
) -> None:
    """On a 320° runway the extended centreline runs out on bearing 140°."""
    placement = final_placement(SAMPLE_RUNWAY, name)
    measured_nm, bearing = distance_and_bearing(SAMPLE_RUNWAY.threshold, placement.position)
    assert measured_nm == pytest.approx(distance_nm, abs=1e-6)
    assert bearing == pytest.approx(140.0, abs=1e-6)
    assert placement.heading_deg == pytest.approx(320.0, abs=1e-9)
    assert placement.altitude_ft == pytest.approx(
        SAMPLE_RUNWAY.elevation_ft + distance_nm * FT_PER_NM_ON_A_THREE_DEGREE_PATH,
        abs=0.01,
    )


def test_ten_nm_final_is_3184_ft_above_the_threshold() -> None:
    """The reference number: tan(3°) * 10 NM * 6076.115486 ft/NM."""
    placement = final_placement(SAMPLE_RUNWAY, "final_10nm")
    assert placement.altitude_ft == pytest.approx(2000.0 + 3184.36, abs=0.01)


def test_short_final_is_one_mile_out_and_318_ft_up() -> None:
    placement = final_placement(SAMPLE_RUNWAY, "short_final")
    measured_nm, _ = distance_and_bearing(SAMPLE_RUNWAY.threshold, placement.position)
    assert measured_nm == pytest.approx(1.0, abs=1e-6)
    assert placement.altitude_ft == pytest.approx(2000.0 + 318.44, abs=0.01)
    assert placement.label == "LEMD 32L short final"


def test_finals_step_down_towards_the_threshold() -> None:
    altitudes = [
        final_placement(SAMPLE_RUNWAY, name).altitude_ft for name in get_args(FinalPlacement)
    ]
    assert altitudes == sorted(altitudes, reverse=True)


def test_final_placement_honours_a_custom_glideslope() -> None:
    """A 5.5° path is tan(5.5°)/tan(3°) times as high at the same distance."""
    standard = final_placement(SAMPLE_RUNWAY, "final_5nm")
    steep = final_placement(SAMPLE_RUNWAY, "final_5nm", glideslope_deg=5.5)
    above_threshold = steep.altitude_ft - SAMPLE_RUNWAY.elevation_ft
    assert above_threshold == pytest.approx(
        5.0 * math.tan(math.radians(5.5)) * FEET_PER_NAUTICAL_MILE, abs=0.01
    )
    assert steep.altitude_ft > standard.altitude_ft
    assert steep.position.latitude == pytest.approx(standard.position.latitude)
    assert steep.position.longitude == pytest.approx(standard.position.longitude)


def test_final_labels_name_the_runway_and_the_distance() -> None:
    assert final_placement(SAMPLE_RUNWAY, "final_20nm").label == "LEMD 32L 20 NM final"
    assert final_placement(NORTH_RUNWAY, "final_3nm").label == "TEST 36 3 NM final"


def test_final_placement_matches_the_underlying_primitive() -> None:
    placement = final_placement(SAMPLE_RUNWAY, "final_8nm")
    assert placement.position == final_approach_point(SAMPLE_RUNWAY, 8.0)


# --------------------------------------------------------------------------
# Circuit legs
# --------------------------------------------------------------------------


#: The four legs paired with their mirror image on the other side.
MIRRORED_PLACEMENTS: tuple[tuple[PatternPlacement, PatternPlacement], ...] = (
    ("left_upwind", "right_upwind"),
    ("left_crosswind", "right_crosswind"),
    ("left_downwind", "right_downwind"),
    ("left_base", "right_base"),
)

#: The three legs that leave the centreline; upwind stays on it.
OFFSET_PLACEMENTS: tuple[tuple[PatternPlacement, PatternPlacement], ...] = MIRRORED_PLACEMENTS[1:]


def test_left_hand_circuit_headings_on_a_northbound_runway() -> None:
    expected: dict[PatternPlacement, float] = {
        "left_upwind": 0.0,
        "left_crosswind": 270.0,
        "left_downwind": 180.0,
        "left_base": 90.0,
    }
    for name, heading in expected.items():
        assert pattern_placement(NORTH_RUNWAY, name).heading_deg == pytest.approx(heading), name


def test_right_hand_circuit_headings_on_a_northbound_runway() -> None:
    expected: dict[PatternPlacement, float] = {
        "right_upwind": 0.0,
        "right_crosswind": 90.0,
        "right_downwind": 180.0,
        "right_base": 270.0,
    }
    for name, heading in expected.items():
        assert pattern_placement(NORTH_RUNWAY, name).heading_deg == pytest.approx(heading), name


def test_left_circuit_is_west_and_right_circuit_is_east_of_a_northbound_runway() -> None:
    for left_name, right_name in OFFSET_PLACEMENTS:
        left = pattern_placement(NORTH_RUNWAY, left_name)
        right = pattern_placement(NORTH_RUNWAY, right_name)
        assert left.position.longitude < NORTH_RUNWAY.threshold.longitude, left_name
        assert right.position.longitude > NORTH_RUNWAY.threshold.longitude, right_name


@pytest.mark.parametrize(("left_name", "right_name"), MIRRORED_PLACEMENTS)
def test_right_hand_circuit_is_the_mirror_image_of_the_left_hand_one(
    left_name: PatternPlacement, right_name: PatternPlacement
) -> None:
    """Mirrored about the centreline: same distance out, opposite side, opposite turns.

    Stated as angles: two bearings mirrored about the runway axis sum to twice
    that axis, and that identity is what a sign error in the pattern geometry
    breaks.
    """
    axis = SAMPLE_RUNWAY.true_bearing_deg
    left = pattern_placement(SAMPLE_RUNWAY, left_name)
    right = pattern_placement(SAMPLE_RUNWAY, right_name)

    left_nm, left_bearing = distance_and_bearing(SAMPLE_RUNWAY.threshold, left.position)
    right_nm, right_bearing = distance_and_bearing(SAMPLE_RUNWAY.threshold, right.position)

    assert left_nm == pytest.approx(right_nm, abs=1e-9)
    assert _angular_gap(left_bearing + right_bearing, 2.0 * axis) < 1e-6
    assert _angular_gap(left.heading_deg + right.heading_deg, 2.0 * axis) < 1e-9
    assert left.altitude_ft == pytest.approx(right.altitude_ft)


@pytest.mark.parametrize(("left_name", "right_name"), OFFSET_PLACEMENTS)
def test_the_two_circuits_are_genuinely_on_opposite_sides(
    left_name: PatternPlacement, right_name: PatternPlacement
) -> None:
    """Guards the mirror test: a pattern collapsed onto the centreline mirrors trivially."""
    axis = SAMPLE_RUNWAY.true_bearing_deg
    _, left_bearing = distance_and_bearing(
        SAMPLE_RUNWAY.threshold, pattern_placement(SAMPLE_RUNWAY, left_name).position
    )
    _, right_bearing = distance_and_bearing(
        SAMPLE_RUNWAY.threshold, pattern_placement(SAMPLE_RUNWAY, right_name).position
    )
    assert _signed_delta(left_bearing, axis) < -5.0
    assert _signed_delta(right_bearing, axis) > 5.0


def test_circuit_defaults_to_1000_ft_above_the_field() -> None:
    assert DEFAULT_PATTERN_ALTITUDE_AGL_FT == 1000.0
    for name in PATTERN_PLACEMENTS:
        placement = pattern_placement(SAMPLE_RUNWAY, name)
        assert placement.altitude_ft == pytest.approx(2000.0 + 1000.0), name


def test_circuit_honours_an_explicit_pattern_altitude() -> None:
    for name in PATTERN_PLACEMENTS:
        placement = pattern_placement(SAMPLE_RUNWAY, name, pattern_altitude_ft=4500.0)
        assert placement.altitude_ft == pytest.approx(4500.0), name


def test_downwind_sits_a_pattern_width_off_the_centreline() -> None:
    placement = pattern_placement(NORTH_RUNWAY, "left_downwind", pattern_width_nm=0.8)
    midfield = point_at_distance_and_bearing(
        NORTH_RUNWAY.threshold,
        NORTH_RUNWAY.length_m / METRES_PER_NAUTICAL_MILE / 2.0,
        NORTH_RUNWAY.true_bearing_deg,
    )
    offset_nm, offset_bearing = distance_and_bearing(midfield, placement.position)
    assert offset_nm == pytest.approx(0.8, abs=1e-6)
    assert offset_bearing == pytest.approx(270.0, abs=0.1)


def test_the_downwind_leg_is_square_to_the_centreline_where_it_leaves_it() -> None:
    """Perpendicular to the axis *at the turn*, not to the axis back at the threshold.

    On a 320° runway the centreline azimuth has already swung by 0.008° over
    the half-runway leg, which is 100 times this tolerance.
    """
    half_length_nm = SAMPLE_RUNWAY.length_m / METRES_PER_NAUTICAL_MILE / 2.0
    midfield = point_at_distance_and_bearing(
        SAMPLE_RUNWAY.threshold, half_length_nm, SAMPLE_RUNWAY.true_bearing_deg
    )
    # The centreline's azimuth at midfield, read off the geodesic back to the
    # threshold rather than assumed to still be 320°.
    _, towards_threshold = distance_and_bearing(midfield, SAMPLE_RUNWAY.threshold)
    axis_at_midfield = towards_threshold + 180.0

    _, to_left = distance_and_bearing(
        midfield, pattern_placement(SAMPLE_RUNWAY, "left_downwind").position
    )
    _, to_right = distance_and_bearing(
        midfield, pattern_placement(SAMPLE_RUNWAY, "right_downwind").position
    )
    assert _angular_gap(to_left, axis_at_midfield - 90.0) < 1e-6
    assert _angular_gap(to_right, axis_at_midfield + 90.0) < 1e-6


def test_base_leg_sits_before_the_threshold() -> None:
    placement = pattern_placement(NORTH_RUNWAY, "left_base", leg_distance_nm=2.0)
    distance_nm, bearing = distance_and_bearing(NORTH_RUNWAY.threshold, placement.position)
    # 2 NM before the threshold, 1 NM to the west: hypotenuse of a 2-by-1 triangle.
    assert distance_nm == pytest.approx(math.hypot(2.0, 1.0), abs=1e-3)
    assert bearing == pytest.approx(180.0 + math.degrees(math.atan2(1.0, 2.0)), abs=0.1)


def test_circuit_labels_name_the_runway_the_side_and_the_leg() -> None:
    assert pattern_placement(SAMPLE_RUNWAY, "left_downwind").label == "LEMD 32L left-hand downwind"
    assert pattern_placement(NORTH_RUNWAY, "right_base").label == "TEST 36 right-hand base"


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def test_resolve_agrees_with_the_specific_resolvers() -> None:
    for name in get_args(FinalPlacement):
        assert resolve_runway_placement(SAMPLE_RUNWAY, name) == final_placement(SAMPLE_RUNWAY, name)
    for name in get_args(PatternPlacement):
        assert resolve_runway_placement(SAMPLE_RUNWAY, name) == pattern_placement(
            SAMPLE_RUNWAY, name
        )


def test_resolve_forwards_the_glideslope_to_finals() -> None:
    placement = resolve_runway_placement(SAMPLE_RUNWAY, "final_10nm", glideslope_deg=2.5)
    assert placement.altitude_ft == pytest.approx(
        2000.0 + 10.0 * math.tan(math.radians(2.5)) * FEET_PER_NAUTICAL_MILE, abs=0.01
    )


def test_resolve_forwards_the_pattern_options_to_circuit_legs() -> None:
    placement = resolve_runway_placement(
        NORTH_RUNWAY,
        "right_downwind",
        pattern_altitude_ft=3300.0,
        pattern_width_nm=2.0,
    )
    assert placement.altitude_ft == pytest.approx(3300.0)
    midfield = point_at_distance_and_bearing(
        NORTH_RUNWAY.threshold,
        NORTH_RUNWAY.length_m / METRES_PER_NAUTICAL_MILE / 2.0,
        NORTH_RUNWAY.true_bearing_deg,
    )
    offset_nm, offset_bearing = distance_and_bearing(midfield, placement.position)
    assert offset_nm == pytest.approx(2.0, abs=1e-6)
    assert offset_bearing == pytest.approx(90.0, abs=0.1)


# --------------------------------------------------------------------------
# Free coordinate
# --------------------------------------------------------------------------


def test_coordinate_placement_is_verbatim() -> None:
    placement = coordinate_placement(MADRID, 137.0)
    assert placement.position == MADRID
    assert placement.altitude_ft == 2000.0
    assert placement.heading_deg == pytest.approx(137.0)
    assert placement.label == "40.4168, -3.7038"


@pytest.mark.parametrize(
    ("given", "expected"), [(450.0, 90.0), (-10.0, 350.0), (360.0, 0.0), (0.0, 0.0)]
)
def test_coordinate_placement_folds_the_heading_into_0_360(given: float, expected: float) -> None:
    assert coordinate_placement(MADRID, given).heading_deg == pytest.approx(expected)


def test_coordinate_placement_defaults_to_north() -> None:
    assert coordinate_placement(MADRID).heading_deg == 0.0


# --------------------------------------------------------------------------
# Waypoint
# --------------------------------------------------------------------------


WAYPOINT = GeoPosition(latitude=40.0, longitude=0.0)
TEN_DEGREES_EAST = GeoPosition(latitude=40.0, longitude=10.0)
TEN_DEGREES_WEST = GeoPosition(latitude=40.0, longitude=-10.0)


def test_waypoint_placement_takes_the_altitude_it_is_given() -> None:
    placement = waypoint_placement(
        GeoPosition(latitude=40.0, longitude=0.0, altitude_ft=99.0), 7000.0
    )
    assert placement.position.latitude == 40.0
    assert placement.position.longitude == 0.0
    assert placement.altitude_ft == 7000.0
    assert placement.label == "over waypoint"


def test_waypoint_placement_uses_the_ident_in_the_label() -> None:
    assert waypoint_placement(WAYPOINT, 5000.0, ident="TOLDO").label == "over TOLDO"


def test_waypoint_without_context_points_north() -> None:
    assert waypoint_placement(WAYPOINT, 5000.0).heading_deg == 0.0


def test_waypoint_heads_towards_the_next_fix() -> None:
    """Due east along the equator is exactly 090°; due north is exactly 000°."""
    on_the_equator = GeoPosition(latitude=0.0, longitude=0.0)
    east = waypoint_placement(
        on_the_equator, 5000.0, next_fix=GeoPosition(latitude=0.0, longitude=5.0)
    )
    assert east.heading_deg == pytest.approx(90.0, abs=1e-9)
    north = waypoint_placement(WAYPOINT, 5000.0, next_fix=GeoPosition(latitude=45.0, longitude=0.0))
    assert north.heading_deg == pytest.approx(0.0, abs=1e-9)


def test_next_fix_heading_is_the_departure_course_not_the_arrival_one() -> None:
    """Leaving 40N/0E for 40N/10E starts south of east: 90° minus the convergence."""
    placement = waypoint_placement(WAYPOINT, 5000.0, next_fix=TEN_DEGREES_EAST)
    _, departure_bearing = distance_and_bearing(WAYPOINT, TEN_DEGREES_EAST)
    assert placement.heading_deg == pytest.approx(departure_bearing, abs=1e-12)
    assert placement.heading_deg < 90.0


def test_waypoint_keeps_the_inbound_course_from_the_previous_fix() -> None:
    """A geodesic between two points at the same latitude arrives as far north
    of the parallel as it departed south of it: the two azimuths sum to 180°.
    Taking the initial bearing instead of the arrival one is off by the whole
    convergence — 6.4° here — so this pins down which one is used."""
    placement = waypoint_placement(WAYPOINT, 5000.0, previous_fix=TEN_DEGREES_WEST)
    _, departure_bearing = distance_and_bearing(TEN_DEGREES_WEST, WAYPOINT)
    assert placement.heading_deg == pytest.approx(180.0 - departure_bearing, abs=1e-9)
    assert placement.heading_deg > 90.0
    # Convergence over 10° of longitude at 40° latitude: 10 * sin(40°) = 6.43°.
    assert placement.heading_deg - departure_bearing == pytest.approx(
        10.0 * math.sin(math.radians(40.0)), abs=0.05
    )


def test_inbound_course_along_a_meridian_is_exact() -> None:
    south = GeoPosition(latitude=35.0, longitude=0.0)
    assert waypoint_placement(WAYPOINT, 5000.0, previous_fix=south).heading_deg == pytest.approx(
        0.0, abs=1e-9
    )


def test_explicit_heading_beats_both_fixes() -> None:
    placement = waypoint_placement(
        WAYPOINT,
        5000.0,
        heading_deg=-45.0,
        next_fix=TEN_DEGREES_EAST,
        previous_fix=TEN_DEGREES_WEST,
    )
    assert placement.heading_deg == pytest.approx(315.0)


def test_next_fix_beats_previous_fix() -> None:
    placement = waypoint_placement(
        WAYPOINT, 5000.0, next_fix=TEN_DEGREES_EAST, previous_fix=TEN_DEGREES_WEST
    )
    assert placement.heading_deg == pytest.approx(
        waypoint_placement(WAYPOINT, 5000.0, next_fix=TEN_DEGREES_EAST).heading_deg
    )
    assert placement.heading_deg < 90.0
