"""Numeric tests for the geodesy primitives.

The numbers here are checked against published values, not against the
implementation: 1 NM = 1852 m exactly, 1 NM = 1852 / 0.3048 ft, and a 3°
glidepath is 318.44 ft per nautical mile.
"""

import math

import pytest

from core.geodesy import (
    FEET_PER_NAUTICAL_MILE,
    METRES_PER_NAUTICAL_MILE,
    PatternLeg,
    distance_and_bearing,
    final_approach_point,
    glideslope_altitude_ft,
    point_at_distance_and_bearing,
    traffic_pattern_point,
)
from core.models import GeoPosition
from tests.conftest import NORTH_RUNWAY, SAMPLE_RUNWAY

MADRID = GeoPosition(latitude=40.4168, longitude=-3.7038, altitude_ft=2000.0)


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
