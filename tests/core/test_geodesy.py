"""Numeric tests for the geodesy primitives and the placements built on them.

The numbers here are checked against published values, not against the
implementation: 1 NM = 1852 m exactly, 1 NM = 1852 / 0.3048 ft, and a 3°
glidepath is 318.44 ft per nautical mile.
"""

import math
from typing import get_args

import pytest
from pydantic import ValidationError

from adapters.fake import FakeSimAdapter
from core.geodesy import (
    APPROACH_CATEGORY_CIRCLING_IAS_KT,
    APPROACH_CATEGORY_VAT_KT,
    BASE_FLAPS_RATIO,
    CIRCUIT_THROTTLE,
    CRUISE_THROTTLE,
    DEFAULT_APPROACH_CATEGORY,
    DEFAULT_PATTERN_ALTITUDE_AGL_FT,
    FEET_PER_MINUTE_PER_KNOT,
    FEET_PER_NAUTICAL_MILE,
    FINAL_DISTANCES_NM,
    FINAL_FLAPS_RATIO,
    FINAL_THROTTLE,
    FINAL_TRIM,
    GROUND_IAS_KT,
    METRES_PER_NAUTICAL_MILE,
    PATTERN_PLACEMENTS,
    RUNWAY_PLACEMENTS,
    SHORT_FINAL_DISTANCE_NM,
    VAT_FROM_VSO,
    ApproachCategory,
    FinalPlacement,
    PatternLeg,
    PatternPlacement,
    Placement,
    RunwayPlacement,
    category_for_vat,
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
from core.models import AircraftState, GeoPosition, Ils
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


def test_waypoint_placement_flies() -> None:
    """A waypoint is airborne by construction, so it gets a manoeuvring speed."""
    assert waypoint_placement(WAYPOINT, 5000.0).ias_kt == 135.0
    assert waypoint_placement(WAYPOINT, 5000.0, category="A").ias_kt == 100.0
    assert waypoint_placement(WAYPOINT, 5000.0, ias_kt=210.0).ias_kt == 210.0


# --------------------------------------------------------------------------
# Speed
#
# The regression these cover: a placement that carries the aircraft's current
# speed hands a parked aeroplane 0 kt, and a 10 NM final at 0 kt ends in
# terrain with the geometry perfect. Measured, not theorised.
# --------------------------------------------------------------------------


#: The aeroplane the instructor starts from: sitting on a stand at LEMD, not
#: moving at all. Every number below has to survive contact with this state.
PARKED = AircraftState(
    latitude=40.4936,
    longitude=-3.5668,
    altitude_ft=2000.0,
    heading_deg=140.0,
    ias_kt=0.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=True,
)


def test_a_placement_cannot_be_built_without_a_speed() -> None:
    """``ias_kt`` is required: forgetting it is a ValidationError, not a 0."""
    with pytest.raises(ValidationError):
        Placement.model_validate(
            {"position": MADRID, "heading_deg": 0.0, "label": "nowhere", "profile": "airborne"}
        )


def test_a_placement_cannot_be_built_without_a_profile() -> None:
    """``profile`` is required for the same reason ``ias_kt`` is: it cannot be
    inferred from the geometry, so a new placement type must answer the
    question rather than inherit a guess."""
    with pytest.raises(ValidationError):
        Placement.model_validate(
            {"position": MADRID, "heading_deg": 0.0, "ias_kt": 120.0, "label": "nowhere"}
        )


def test_a_placement_rejects_a_negative_speed() -> None:
    with pytest.raises(ValidationError):
        Placement(
            position=MADRID, heading_deg=0.0, ias_kt=-1.0, label="nowhere", profile="airborne"
        )


def test_the_category_tables_cover_every_category() -> None:
    categories = get_args(ApproachCategory)
    assert categories == ("A", "B", "C", "D", "E")
    assert tuple(APPROACH_CATEGORY_VAT_KT) == categories
    assert tuple(APPROACH_CATEGORY_CIRCLING_IAS_KT) == categories
    assert DEFAULT_APPROACH_CATEGORY in categories


def test_the_published_category_speeds() -> None:
    """The tops of the ICAO PANS-OPS Vat bands, and the circling maxima.

    Pinned as literals because they are the whole defence against the defect:
    if someone edits them, they should have to say so.
    """
    assert dict(APPROACH_CATEGORY_VAT_KT) == {
        "A": 90.0,
        "B": 120.0,
        "C": 140.0,
        "D": 165.0,
        "E": 210.0,
    }
    assert dict(APPROACH_CATEGORY_CIRCLING_IAS_KT) == {
        "A": 100.0,
        "B": 135.0,
        "C": 180.0,
        "D": 205.0,
        "E": 240.0,
    }


def test_every_category_speed_is_a_flying_speed() -> None:
    """Even the slowest category is 90 kt: no table entry can produce a stall."""
    for category in get_args(ApproachCategory):
        assert APPROACH_CATEGORY_VAT_KT[category] >= 90.0, category
        assert APPROACH_CATEGORY_CIRCLING_IAS_KT[category] >= 100.0, category


def test_heavier_categories_fly_faster() -> None:
    speeds = [APPROACH_CATEGORY_VAT_KT[c] for c in get_args(ApproachCategory)]
    assert speeds == sorted(speeds)
    assert speeds[0] < speeds[-1]


def test_a_circuit_is_flown_faster_than_it_is_landed() -> None:
    for category in get_args(ApproachCategory):
        assert APPROACH_CATEGORY_CIRCLING_IAS_KT[category] > APPROACH_CATEGORY_VAT_KT[category]


@pytest.mark.parametrize(
    ("vat_kt", "expected"),
    [
        # Either side of every published band boundary: A <91, B 91-120,
        # C 121-140, D 141-165, E 166-210.
        (90.0, "A"),
        (91.0, "B"),
        (120.0, "B"),
        (121.0, "C"),
        (140.0, "C"),
        (141.0, "D"),
        (165.0, "D"),
        (166.0, "E"),
        (210.0, "E"),
    ],
)
def test_the_category_bands_by_vat(vat_kt: float, expected: ApproachCategory) -> None:
    """The PANS-OPS bands, walked at their boundaries — off-by-one is the whole risk."""
    assert category_for_vat(vat_kt) == expected


def test_a_vat_above_the_table_clamps_to_e() -> None:
    """There is no category F: the table ends at 210 kt, and faster is still E."""
    assert category_for_vat(211.0) == "E"
    assert category_for_vat(400.0) == "E"


@pytest.mark.parametrize("vat_kt", [0.0, -1.0])
def test_a_non_positive_vat_is_a_caller_bug(vat_kt: float) -> None:
    """Zero cannot be laundered into 'category A' — upstream arithmetic went wrong."""
    with pytest.raises(ValueError, match="positive"):
        category_for_vat(vat_kt)


def test_the_band_tops_agree_with_the_vat_table() -> None:
    """Two statements of the same published table must never drift apart:
    every category's top-of-band speed classifies as that category."""
    for category, top_kt in APPROACH_CATEGORY_VAT_KT.items():
        assert category_for_vat(top_kt) == category


def test_a_c172_stall_speed_derives_category_a() -> None:
    """Issue #82's motivating example: Vso 48 kt → V_AT 62.4 kt → category A —
    not the B default that put a trainer on final at 120 kt."""
    assert VAT_FROM_VSO == 1.3
    vat_kt = VAT_FROM_VSO * 48.0
    assert vat_kt == pytest.approx(62.4)
    assert category_for_vat(vat_kt) == "A"


@pytest.mark.parametrize("name", list(FINAL_DISTANCES_NM))
def test_every_final_commands_an_approach_speed(name: FinalPlacement) -> None:
    """120 kt, not 0 — the default category is B and B's Vat band tops at 120."""
    assert DEFAULT_APPROACH_CATEGORY == "B"
    assert final_placement(SAMPLE_RUNWAY, name).ias_kt == 120.0


@pytest.mark.parametrize("name", list(PATTERN_PLACEMENTS))
def test_every_circuit_leg_commands_a_circling_speed(name: PatternPlacement) -> None:
    assert pattern_placement(SAMPLE_RUNWAY, name).ias_kt == 135.0


@pytest.mark.parametrize("name", list(RUNWAY_PLACEMENTS))
def test_no_runway_placement_is_ever_stationary(name: RunwayPlacement) -> None:
    """The acceptance criterion, stated over the whole catalogue."""
    assert resolve_runway_placement(SAMPLE_RUNWAY, name).ias_kt >= 90.0


def test_a_trainer_and_an_airliner_do_not_fly_the_same_final() -> None:
    """The reason the default is a category and not a number."""
    trainer = final_placement(SAMPLE_RUNWAY, "final_10nm", category="A")
    airliner = final_placement(SAMPLE_RUNWAY, "final_10nm", category="D")
    assert trainer.ias_kt == 90.0
    assert airliner.ias_kt == 165.0
    # Same point in space, different speed: only the speed depends on the type.
    assert trainer.position == airliner.position
    assert trainer.heading_deg == airliner.heading_deg


def test_an_explicit_speed_beats_the_category() -> None:
    """The 90 kt that flew a real approach at LEMD, commanded over a category D."""
    placement = final_placement(SAMPLE_RUNWAY, "final_10nm", ias_kt=90.0, category="D")
    assert placement.ias_kt == 90.0
    assert pattern_placement(SAMPLE_RUNWAY, "left_downwind", ias_kt=75.0).ias_kt == 75.0


def test_resolve_forwards_the_speed_and_the_category() -> None:
    assert resolve_runway_placement(SAMPLE_RUNWAY, "final_5nm", ias_kt=131.0).ias_kt == 131.0
    assert resolve_runway_placement(SAMPLE_RUNWAY, "final_5nm", category="C").ias_kt == 140.0
    assert resolve_runway_placement(SAMPLE_RUNWAY, "left_base", category="C").ias_kt == 180.0


def test_a_free_coordinate_is_stationary_until_told_otherwise() -> None:
    """Nothing is inferred from a bare lat/lon, including whether it is flying."""
    assert GROUND_IAS_KT == 0.0
    assert coordinate_placement(MADRID, 137.0).ias_kt == 0.0
    assert coordinate_placement(MADRID, 137.0, ias_kt=250.0).ias_kt == 250.0


def test_to_setup_carries_the_three_fields_a_placement_determines() -> None:
    placement = final_placement(SAMPLE_RUNWAY, "final_10nm")
    setup = placement.to_setup()
    assert setup.ias_kt == 120.0
    assert setup.heading_deg == pytest.approx(320.0)
    assert setup.altitude_ft == pytest.approx(
        2000.0 + 10.0 * FT_PER_NM_ON_A_THREE_DEGREE_PATH, abs=0.1
    )


def test_to_setup_leaves_what_the_profile_does_not_determine_untouched() -> None:
    """The profile owns the configuration; it does not own the aircraft.

    Mass, spoilers, autobrake, pitch, NAV2 and the whole autopilot block are
    not part of any profile and must stay ``None``, which an adapter reads as
    *do not touch*. Stated as the exact set of fields a final emits, so a field
    quietly added to a profile has to be declared here too.
    """
    setup = final_placement(SAMPLE_RUNWAY, "short_final").to_setup()
    set_fields = {name for name, value in setup.model_dump().items() if value is not None}
    assert set_fields == {
        "altitude_ft",
        "heading_deg",
        "ias_kt",
        "vertical_speed_fpm",
        "roll_deg",
        "gear_down",
        "flaps_ratio",
        "elevator_trim_ratio",
        "throttle_ratio",
        "lights",
    }


# --------------------------------------------------------------------------
# Profiles
#
# Speed is only half of issue #39's lesson. The Phase 1 live validation placed
# a C172 on a perfect 10 NM final at the right speed and still handed over an
# unflyable aeroplane: parked trim, drifting throttle, no descent rate, and a
# divergent phugoid within 20 s (#81). The profile is the rest of the hand-off
# (#8): the configuration that makes the placement *stabilised*.
# --------------------------------------------------------------------------


#: The ILS the sample runway would publish, hand-written like everything else
#: here (hard rule 4). The magnetic course is deliberately not the true one, so
#: a test that confuses the two frames fails rather than passes by luck.
SAMPLE_ILS = Ils(
    airport_icao="LEMD",
    runway_ident="32L",
    localizer_ident="IML",
    frequency_khz=110300,
    localizer_position=GeoPosition(latitude=40.49, longitude=-3.59, altitude_ft=2000.0),
    localizer_true_deg=320.0,
    localizer_mag_deg=323.0,
    glideslope_deg=3.0,
)


def test_feet_per_minute_per_knot() -> None:
    """One knot covers 6076.115486 / 60 = 101.2686 ft of ground per minute."""
    assert pytest.approx(101.2686, abs=1e-4) == FEET_PER_MINUTE_PER_KNOT


def test_every_constructor_answers_the_profile_question() -> None:
    """``profile`` has no default, so each constructor states what it builds."""
    assert final_placement(SAMPLE_RUNWAY, "final_10nm").profile == "final"
    assert pattern_placement(SAMPLE_RUNWAY, "left_base").profile == "circuit"
    assert waypoint_placement(WAYPOINT, 5000.0).profile == "airborne"
    # 0 kt is definitionally not flying, so the coordinate's profile follows
    # its speed: the stationary default is ground, anything else is airborne.
    assert coordinate_placement(MADRID).profile == "ground"
    assert coordinate_placement(MADRID, ias_kt=250.0).profile == "airborne"


def test_a_pattern_placement_knows_its_leg() -> None:
    for name, (leg, _side) in PATTERN_PLACEMENTS.items():
        assert pattern_placement(SAMPLE_RUNWAY, name).pattern_leg == leg, name


def test_a_final_carries_its_glideslope_and_its_ils() -> None:
    bare = final_placement(SAMPLE_RUNWAY, "final_10nm", glideslope_deg=3.5)
    assert bare.glideslope_deg == 3.5
    assert bare.ils is None
    tuned = final_placement(SAMPLE_RUNWAY, "final_10nm", ils=SAMPLE_ILS)
    assert tuned.ils == SAMPLE_ILS
    assert tuned.glideslope_deg == 3.0


def test_resolve_passes_the_ils_to_finals_and_not_to_circuits() -> None:
    """A circuit is flown visually; only the final gets the radios."""
    assert resolve_runway_placement(SAMPLE_RUNWAY, "final_5nm", ils=SAMPLE_ILS).ils == SAMPLE_ILS
    assert resolve_runway_placement(SAMPLE_RUNWAY, "left_base", ils=SAMPLE_ILS).ils is None


def test_a_final_is_configured_to_fly_the_approach() -> None:
    """Gear down, approach flap, approach power, nose-up trim, wings level."""
    setup = final_placement(SAMPLE_RUNWAY, "final_10nm").to_setup()
    assert setup.gear_down is True
    assert setup.flaps_ratio == FINAL_FLAPS_RATIO == 0.5
    assert setup.throttle_ratio == FINAL_THROTTLE == 0.30
    assert setup.elevator_trim_ratio == FINAL_TRIM == 0.10
    assert setup.roll_deg == 0.0
    assert setup.lights is not None
    assert setup.lights.landing is True


def test_a_final_descends_on_its_glidepath() -> None:
    """120 kt on a 3° slope: 120 · 101.2686 ft/min/kt · tan 3° = 637 fpm down."""
    setup = final_placement(SAMPLE_RUNWAY, "final_10nm").to_setup()
    assert setup.vertical_speed_fpm is not None
    assert setup.vertical_speed_fpm < 0.0
    assert setup.vertical_speed_fpm == pytest.approx(
        -120.0 * FEET_PER_MINUTE_PER_KNOT * math.tan(math.radians(3.0))
    )


def test_the_descent_arithmetic_matches_the_rule_of_thumb() -> None:
    """3° at 90 kt is the pilot's ~480 fpm — the published cross-check."""
    setup = final_placement(SAMPLE_RUNWAY, "final_10nm", ias_kt=90.0).to_setup()
    assert setup.vertical_speed_fpm == pytest.approx(-478.0, abs=1.0)


def test_a_steeper_slope_needs_a_faster_descent() -> None:
    standard = final_placement(SAMPLE_RUNWAY, "final_5nm").to_setup()
    steep = final_placement(SAMPLE_RUNWAY, "final_5nm", glideslope_deg=5.5).to_setup()
    assert standard.vertical_speed_fpm is not None
    assert steep.vertical_speed_fpm is not None
    assert steep.vertical_speed_fpm < standard.vertical_speed_fpm < 0.0


def test_a_final_on_an_ils_tunes_the_radios() -> None:
    """NAV1 takes the frequency and the OBS the MAGNETIC front course —
    an OBS is magnetic on the aeroplane, not true like the geometry here."""
    setup = final_placement(SAMPLE_RUNWAY, "final_10nm", ils=SAMPLE_ILS).to_setup()
    assert setup.nav1_freq_khz == 110300
    assert setup.obs1_deg == 323.0


def test_a_final_without_an_ils_leaves_the_radios_alone() -> None:
    setup = final_placement(SAMPLE_RUNWAY, "final_10nm").to_setup()
    assert setup.nav1_freq_khz is None
    assert setup.obs1_deg is None


def test_the_circuit_configures_as_it_comes_round() -> None:
    """Gear on downwind and base, first notch of flap on base, clean before."""
    dirty: tuple[PatternPlacement, ...] = (
        "left_downwind",
        "right_downwind",
        "left_base",
        "right_base",
    )
    clean: tuple[PatternPlacement, ...] = (
        "left_upwind",
        "right_upwind",
        "left_crosswind",
        "right_crosswind",
    )
    for name in dirty:
        assert pattern_placement(SAMPLE_RUNWAY, name).to_setup().gear_down is True, name
    for name in clean:
        assert pattern_placement(SAMPLE_RUNWAY, name).to_setup().gear_down is False, name
    assert pattern_placement(SAMPLE_RUNWAY, "left_base").to_setup().flaps_ratio == BASE_FLAPS_RATIO
    assert pattern_placement(SAMPLE_RUNWAY, "left_downwind").to_setup().flaps_ratio == 0.0


def test_a_circuit_leg_is_flown_level_at_circuit_power() -> None:
    setup = pattern_placement(SAMPLE_RUNWAY, "left_downwind").to_setup()
    assert setup.throttle_ratio == CIRCUIT_THROTTLE == 0.50
    assert setup.vertical_speed_fpm == 0.0
    assert setup.roll_deg == 0.0
    assert setup.elevator_trim_ratio == 0.0


def test_an_airborne_placement_is_clean_and_level_at_cruise_power() -> None:
    setup = waypoint_placement(WAYPOINT, 5000.0).to_setup()
    assert setup.gear_down is False
    assert setup.flaps_ratio == 0.0
    assert setup.throttle_ratio == CRUISE_THROTTLE == 0.60
    assert setup.vertical_speed_fpm == 0.0
    assert setup.roll_deg == 0.0


def test_a_ground_placement_idles_and_leaves_the_attitude_to_the_terrain() -> None:
    """Gear down and everything at idle — but roll and vertical speed stay
    ``None``: the aircraft is sitting on its gear, and both belong to the
    terrain rather than to the placement."""
    setup = coordinate_placement(MADRID).to_setup()
    assert setup.gear_down is True
    assert setup.flaps_ratio == 0.0
    assert setup.throttle_ratio == 0.0
    assert setup.vertical_speed_fpm is None
    assert setup.roll_deg is None


async def test_a_parked_aircraft_placed_on_a_ten_nm_final_ends_up_flying() -> None:
    """The regression, end to end against the reference adapter.

    A stationary aeroplane is placed on a 10 NM final and then left to fly: one
    minute later it is 2 NM closer to the threshold. Before this change it was
    still at 0 kt and 10 NM out, sinking.
    """
    adapter = FakeSimAdapter(initial_state=PARKED)
    await adapter.connect()
    assert (await adapter.get_aircraft_state()).ias_kt == 0.0

    placement = resolve_runway_placement(SAMPLE_RUNWAY, "final_10nm")
    # The Position Manager pipeline: configure, then move.
    await adapter.apply_setup(placement.to_setup())
    await adapter.set_position(placement.position, placement.heading_deg)

    placed = await adapter.get_aircraft_state()
    assert placed.ias_kt == 120.0
    assert placed.altitude_ft == pytest.approx(
        2000.0 + 10.0 * FT_PER_NM_ON_A_THREE_DEGREE_PATH, abs=0.1
    )
    at_placement_nm, _ = distance_and_bearing(
        GeoPosition(latitude=placed.latitude, longitude=placed.longitude),
        SAMPLE_RUNWAY.threshold,
    )
    assert at_placement_nm == pytest.approx(10.0, abs=1e-6)

    # One minute of flight at 120 kt is 2 NM, and it is 2 NM towards the runway.
    flown = await anext(adapter.stream_state(60.0))
    after_a_minute_nm, _ = distance_and_bearing(
        GeoPosition(latitude=flown.latitude, longitude=flown.longitude),
        SAMPLE_RUNWAY.threshold,
    )
    assert after_a_minute_nm == pytest.approx(8.0, abs=0.01)


async def test_the_defect_reproduced_when_the_speed_is_not_commanded() -> None:
    """Teleporting without applying the setup is exactly the old behaviour.

    Kept as the counter-example: it pins what ``to_setup`` is for, so nobody
    "simplifies" the pipeline back into the crash.
    """
    adapter = FakeSimAdapter(initial_state=PARKED)
    await adapter.connect()
    placement = resolve_runway_placement(SAMPLE_RUNWAY, "final_10nm")
    await adapter.set_position(placement.position, placement.heading_deg)

    stalled = await adapter.get_aircraft_state()
    assert stalled.ias_kt == 0.0
    drifted = await anext(adapter.stream_state(60.0))
    still_out_nm, _ = distance_and_bearing(
        GeoPosition(latitude=drifted.latitude, longitude=drifted.longitude),
        SAMPLE_RUNWAY.threshold,
    )
    assert still_out_nm == pytest.approx(10.0, abs=1e-6)
