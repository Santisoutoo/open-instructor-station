"""Numeric tests for the placements driven by published navdata.

Holding patterns and procedure legs, i.e. the half of the placement catalogue
that reads its geometry off ``earth_hold.dat`` and the CIFP instead of deriving
it from a runway. The runway-relative placements live in ``test_geodesy.py``.

The numbers are checked against published values and hand geometry, not against
the implementation: rate one is a 360° turn in two minutes (so a 120 kt turn has
a circumference of 4 NM and a radius of 4/2pi = 0.6366 NM), an aircraft
indicating 210 kt at 10 000 ft is truly doing 244 kt, and the ICAO entry sectors
are 180°, 110° and 70° wide.
"""

import ast
import math
from pathlib import Path
from typing import get_args

import pytest
from geographiclib.geodesic import Geodesic

from core.atmosphere import tas_from_ias
from core.geodesy import (
    APPROACH_CATEGORY_CIRCLING_IAS_KT,
    APPROACH_CATEGORY_VAT_KT,
    DEFAULT_HOLD_ENTRY_DISTANCE_NM,
    HOLD_LEG_TIME_ALTITUDE_FT,
    HOLD_LEG_TIME_HIGH_MIN,
    HOLD_LEG_TIME_LOW_MIN,
    HOLD_MAX_BANK_DEG,
    HOLD_PLACEMENTS,
    HOLD_RATE_OF_TURN_DEG_PER_S,
    PARALLEL_ENTRY_SECTOR_DEG,
    TEARDROP_ENTRY_SECTOR_DEG,
    HoldEntry,
    HoldPlacement,
    distance_and_bearing,
    hold_entry,
    hold_entry_placement,
    hold_leg_length_nm,
    hold_placement,
    holding_entry,
    holding_pattern_point,
    point_at_distance_and_bearing,
    positionable_legs,
    procedure_leg_placement,
    procedure_placement,
    true_from_magnetic,
    turn_radius_nm,
    waypoint_placement,
)
from core.models import GeoPosition
from core.navdata.models import (
    AltitudeConstraint,
    Hold,
    Procedure,
    ProcedureLeg,
    SpeedConstraint,
    Waypoint,
)

# --------------------------------------------------------------------------
# Fixtures: a hold on a meridian, so "east" and "south" are readable by eye
# --------------------------------------------------------------------------

FIX = Waypoint(
    ident="TOBEK",
    kind="fix",
    position=GeoPosition(latitude=40.0, longitude=-3.0),
    region_code="LE",
)

#: Inbound course due north, right turns: the racetrack lies south of the fix
#: and east of the inbound leg. Held between 6000 and 10 000 ft.
NORTH_HOLD = Hold(
    fix=FIX,
    inbound_course_mag_deg=0.0,
    turn_direction="R",
    leg_time_min=1.0,
    min_altitude_ft=6000.0,
    max_altitude_ft=10_000.0,
)

LEFT_HOLD = NORTH_HOLD.model_copy(update={"turn_direction": "L"})

#: No variation anywhere below, so magnetic and true coincide and the geometry
#: can be read straight off the compass. The tests that care about the
#: conversion state their own variation.
NO_VARIATION = 0.0


# --------------------------------------------------------------------------
# Magnetic to true
# --------------------------------------------------------------------------


def test_true_from_magnetic_adds_an_easterly_variation() -> None:
    """Variation is positive east, so true = magnetic + variation."""
    assert true_from_magnetic(100.0, 3.0) == pytest.approx(103.0)


def test_true_from_magnetic_subtracts_a_westerly_variation() -> None:
    """KJFK holds at 242° magnetic with ~13°W: 229° true."""
    assert true_from_magnetic(242.0, -13.0) == pytest.approx(229.0)


@pytest.mark.parametrize(
    ("magnetic", "variation", "expected"),
    [(355.0, 10.0, 5.0), (5.0, -10.0, 355.0), (0.0, 0.0, 0.0), (360.0, 0.0, 0.0)],
)
def test_true_from_magnetic_folds_into_0_360(
    magnetic: float, variation: float, expected: float
) -> None:
    assert true_from_magnetic(magnetic, variation) == pytest.approx(expected)


# --------------------------------------------------------------------------
# Entry sectors
# --------------------------------------------------------------------------


#: The textbook picture, for a standard hold whose inbound course is 360°.
RIGHT_HAND_SECTORS: tuple[tuple[float, HoldEntry], ...] = (
    (0.0, "direct"),
    (90.0, "direct"),
    (179.9, "direct"),
    (180.0, "parallel"),
    (250.0, "parallel"),
    (289.9, "parallel"),
    (290.0, "teardrop"),
    (330.0, "teardrop"),
    (359.9, "teardrop"),
)


@pytest.mark.parametrize(("arrival_deg", "expected"), RIGHT_HAND_SECTORS)
def test_right_hand_entry_sectors(arrival_deg: float, expected: HoldEntry) -> None:
    assert holding_entry(0.0, arrival_deg) == expected


@pytest.mark.parametrize(("arrival_deg", "expected"), RIGHT_HAND_SECTORS)
def test_a_left_hand_hold_mirrors_every_sector(arrival_deg: float, expected: HoldEntry) -> None:
    """The non-standard pattern is the standard one reflected about the inbound course."""
    assert holding_entry(0.0, -arrival_deg, "L") == expected


def test_the_sectors_are_180_110_and_70_degrees_wide() -> None:
    """The published widths, counted a degree at a time over the whole compass."""
    entries = [holding_entry(0.0, float(degree)) for degree in range(360)]
    assert entries.count("direct") == 180
    assert entries.count("parallel") == PARALLEL_ENTRY_SECTOR_DEG == 110
    assert entries.count("teardrop") == TEARDROP_ENTRY_SECTOR_DEG == 70


def test_the_sectors_rotate_with_the_inbound_course() -> None:
    """Nothing about a sector is tied to north: it is all relative to the course."""
    for inbound in (0.0, 137.0, 285.0, 359.0):
        assert holding_entry(inbound, inbound + 45.0) == "direct"
        assert holding_entry(inbound, inbound + 200.0) == "parallel"
        assert holding_entry(inbound, inbound + 300.0) == "teardrop"


def test_every_arrival_course_has_exactly_one_entry() -> None:
    valid = set(get_args(HoldEntry))
    for degree in range(0, 3600):
        assert holding_entry(41.7, degree / 10.0, "L") in valid


def test_hold_entry_reads_the_published_course() -> None:
    """The published course is magnetic; the arrival course is true."""
    assert hold_entry(NORTH_HOLD, 90.0, magnetic_variation_deg=NO_VARIATION) == "direct"
    assert hold_entry(NORTH_HOLD, 200.0, magnetic_variation_deg=NO_VARIATION) == "parallel"
    assert hold_entry(NORTH_HOLD, 300.0, magnetic_variation_deg=NO_VARIATION) == "teardrop"


def test_variation_moves_the_sector_boundaries() -> None:
    """A 30° variation is two sector boundaries' worth of error.

    Arriving on 200° true is a parallel entry into a hold whose inbound course
    is 0° true, and a direct one into the same *published* hold where the
    variation is 30°E — because that hold's inbound course is 30° true.
    """
    assert hold_entry(NORTH_HOLD, 200.0, magnetic_variation_deg=0.0) == "parallel"
    assert hold_entry(NORTH_HOLD, 200.0, magnetic_variation_deg=30.0) == "direct"


def test_a_left_hand_published_hold_uses_its_own_turn_direction() -> None:
    assert hold_entry(NORTH_HOLD, 300.0, magnetic_variation_deg=NO_VARIATION) == "teardrop"
    assert hold_entry(LEFT_HOLD, 300.0, magnetic_variation_deg=NO_VARIATION) == "direct"


# --------------------------------------------------------------------------
# Turn radius
# --------------------------------------------------------------------------


def test_rate_one_at_120_kt_is_a_four_mile_circle() -> None:
    """A 360° at 3°/s takes two minutes, which at 120 kt is 4 NM of arc."""
    radius_nm = turn_radius_nm(120.0)
    assert 2.0 * math.pi * radius_nm == pytest.approx(4.0, abs=1e-9)
    assert radius_nm == pytest.approx(0.63662, abs=1e-5)


def test_a_jet_cannot_hold_rate_one_within_25_degrees_of_bank() -> None:
    """At 210 kt true the bank limit takes over: 1.378 NM, not 1.114 NM."""
    rate_one_radius_nm = 210.0 / (20.0 * math.pi * HOLD_RATE_OF_TURN_DEG_PER_S)
    assert rate_one_radius_nm == pytest.approx(1.1141, abs=1e-4)
    assert turn_radius_nm(210.0) == pytest.approx(1.3781, abs=1e-4)
    assert turn_radius_nm(210.0) > rate_one_radius_nm


def test_the_bank_limited_radius_is_the_textbook_one() -> None:
    """``v^2 / (g tan phi)``, computed independently in metric units."""
    speed_m_per_s = 240.0 * 1852.0 / 3600.0
    expected_nm = speed_m_per_s**2 / (9.80665 * math.tan(math.radians(HOLD_MAX_BANK_DEG))) / 1852.0
    assert expected_nm == pytest.approx(1.8, abs=1e-3)
    assert turn_radius_nm(240.0) == pytest.approx(expected_nm, abs=1e-9)


def test_the_two_criteria_cross_at_about_170_kt() -> None:
    """Below the crossover the rate binds, above it the bank does."""
    assert turn_radius_nm(150.0) == pytest.approx(150.0 / (60.0 * math.pi), abs=1e-9)
    assert turn_radius_nm(190.0) > 190.0 / (60.0 * math.pi)


def test_a_faster_aircraft_needs_more_room() -> None:
    radii = [turn_radius_nm(speed) for speed in (60.0, 120.0, 180.0, 240.0)]
    assert radii == sorted(radii)


def test_a_stationary_aircraft_has_no_radius() -> None:
    assert turn_radius_nm(0.0) == 0.0


@pytest.mark.parametrize(
    ("tas_kt", "rate", "bank"),
    [(-1.0, 3.0, 25.0), (120.0, 0.0, 25.0), (120.0, -3.0, 25.0), (120.0, 3.0, 0.0)],
)
def test_a_turn_that_is_not_a_turn_is_refused(tas_kt: float, rate: float, bank: float) -> None:
    with pytest.raises(ValueError):
        turn_radius_nm(tas_kt, rate, bank)


def test_a_ninety_degree_bank_is_refused() -> None:
    """The vertical component of lift is gone: the radius is not merely small."""
    with pytest.raises(ValueError, match="90"):
        turn_radius_nm(120.0, HOLD_RATE_OF_TURN_DEG_PER_S, 90.0)


# --------------------------------------------------------------------------
# Leg length
# --------------------------------------------------------------------------


def test_a_published_distance_leg_is_taken_verbatim() -> None:
    """A DME hold states its length; no speed enters into it."""
    dme_hold = NORTH_HOLD.model_copy(update={"leg_time_min": None, "leg_length_nm": 7.0})
    assert hold_leg_length_nm(dme_hold, 150.0, 6000.0) == 7.0
    assert hold_leg_length_nm(dme_hold, 250.0, 20_000.0) == 7.0


def test_a_published_time_leg_becomes_a_distance_at_that_speed() -> None:
    """One minute at 150 kt true is 2.5 NM."""
    assert hold_leg_length_nm(NORTH_HOLD, 150.0, 6000.0) == pytest.approx(2.5)


def test_a_ninety_second_leg_is_half_as_long_again() -> None:
    long_leg = NORTH_HOLD.model_copy(update={"leg_time_min": 1.5})
    assert hold_leg_length_nm(long_leg, 150.0, 6000.0) == pytest.approx(3.75)


def test_an_unstated_leg_takes_the_standard_time_for_the_altitude() -> None:
    """One minute at or below 14 000 ft, a minute and a half above it."""
    bare = NORTH_HOLD.model_copy(update={"leg_time_min": None})
    assert HOLD_LEG_TIME_LOW_MIN == 1.0
    assert HOLD_LEG_TIME_HIGH_MIN == 1.5
    assert HOLD_LEG_TIME_ALTITUDE_FT == 14_000.0
    assert hold_leg_length_nm(bare, 180.0, 14_000.0) == pytest.approx(3.0)
    assert hold_leg_length_nm(bare, 180.0, 14_001.0) == pytest.approx(4.5)


# --------------------------------------------------------------------------
# Racetrack geometry
# --------------------------------------------------------------------------


def _pattern(placement: HoldPlacement, turn: str = "R") -> tuple[GeoPosition, float]:
    """The four-mile-by-two-mile racetrack used by the geometry tests."""
    return holding_pattern_point(
        FIX.position,
        0.0,
        placement,
        7000.0,
        leg_length_nm=4.0,
        width_nm=2.0,
        turn_direction="R" if turn == "R" else "L",
    )


def test_the_fix_is_the_origin_of_the_pattern() -> None:
    position, heading = _pattern("hold_fix")
    assert position.latitude == pytest.approx(FIX.position.latitude, abs=1e-12)
    assert position.longitude == pytest.approx(FIX.position.longitude, abs=1e-12)
    assert heading == pytest.approx(0.0)


def test_the_inbound_leg_runs_back_from_the_fix_on_the_inbound_course() -> None:
    """Inbound course 360°, so the inbound leg is due south of the fix."""
    position, heading = _pattern("hold_inbound")
    distance_nm, bearing = distance_and_bearing(FIX.position, position)
    assert distance_nm == pytest.approx(4.0, abs=1e-6)
    assert bearing == pytest.approx(180.0, abs=1e-9)
    assert heading == pytest.approx(0.0)


def test_the_outbound_leg_is_abeam_the_fix_on_the_holding_side() -> None:
    """Right turns from a northbound inbound leg put the outbound leg east."""
    position, heading = _pattern("hold_outbound")
    distance_nm, bearing = distance_and_bearing(FIX.position, position)
    assert distance_nm == pytest.approx(2.0, abs=1e-6)
    assert bearing == pytest.approx(90.0, abs=1e-9)
    assert heading == pytest.approx(180.0)


def test_the_end_of_the_outbound_leg_closes_the_racetrack() -> None:
    """A 4 NM leg 2 NM to the side: the diagonal of a 4-by-2 rectangle."""
    position, heading = _pattern("hold_outbound_end")
    distance_nm, bearing = distance_and_bearing(FIX.position, position)
    assert distance_nm == pytest.approx(math.hypot(4.0, 2.0), abs=1e-3)
    assert bearing == pytest.approx(180.0 - math.degrees(math.atan2(2.0, 4.0)), abs=0.1)
    assert heading == pytest.approx(180.0)


def test_the_two_straight_legs_are_a_pattern_width_apart_and_parallel() -> None:
    inbound, inbound_heading = _pattern("hold_inbound")
    outbound_end, outbound_heading = _pattern("hold_outbound_end")
    separation_nm, bearing = distance_and_bearing(inbound, outbound_end)
    assert separation_nm == pytest.approx(2.0, abs=1e-6)
    assert bearing == pytest.approx(90.0, abs=1e-6)
    assert abs(inbound_heading - outbound_heading) == pytest.approx(180.0)


def test_a_left_hand_hold_is_the_mirror_image() -> None:
    for placement in HOLD_PLACEMENTS:
        right, right_heading = _pattern(placement)
        left, left_heading = _pattern(placement, turn="L")
        right_nm, right_bearing = distance_and_bearing(FIX.position, right)
        left_nm, left_bearing = distance_and_bearing(FIX.position, left)
        assert left_nm == pytest.approx(right_nm, abs=1e-9), placement
        # Mirrored about the 360° inbound course, two bearings sum to 360°.
        assert (left_bearing + right_bearing) % 360.0 == pytest.approx(0.0, abs=1e-6), placement
        assert left_heading == pytest.approx(right_heading), placement


def test_the_whole_pattern_is_level() -> None:
    for placement in HOLD_PLACEMENTS:
        position, _ = _pattern(placement)
        assert position.altitude_ft == pytest.approx(7000.0), placement


def test_the_pattern_rotates_with_the_inbound_course() -> None:
    """Inbound course 270°: the aircraft flies west to the fix, so the inbound
    leg lies east of it and a right-hand pattern lies north."""
    inbound, inbound_heading = holding_pattern_point(
        FIX.position, 270.0, "hold_inbound", 7000.0, 4.0, 2.0
    )
    _, bearing = distance_and_bearing(FIX.position, inbound)
    assert bearing == pytest.approx(90.0, abs=0.1)
    assert inbound_heading == pytest.approx(270.0)

    outbound, outbound_heading = holding_pattern_point(
        FIX.position, 270.0, "hold_outbound", 7000.0, 4.0, 2.0
    )
    _, outbound_bearing = distance_and_bearing(FIX.position, outbound)
    assert outbound_bearing == pytest.approx(0.0, abs=0.1)
    assert outbound_heading == pytest.approx(90.0)


# --------------------------------------------------------------------------
# Hold placements
# --------------------------------------------------------------------------


def test_a_hold_placement_defaults_to_the_fix() -> None:
    placement = hold_placement(NORTH_HOLD, magnetic_variation_deg=NO_VARIATION)
    assert placement.position.latitude == pytest.approx(40.0, abs=1e-12)
    assert placement.position.longitude == pytest.approx(-3.0, abs=1e-12)
    assert placement.heading_deg == pytest.approx(0.0)
    assert placement.label == "TOBEK hold — over the fix"


def test_a_hold_placement_takes_the_published_lower_altitude() -> None:
    """A hold is protected between two altitudes; an aircraft joins at the bottom."""
    assert hold_placement(NORTH_HOLD, magnetic_variation_deg=NO_VARIATION).altitude_ft == 6000.0


def test_an_explicit_altitude_beats_the_published_one() -> None:
    placement = hold_placement(NORTH_HOLD, magnetic_variation_deg=NO_VARIATION, altitude_ft=9000.0)
    assert placement.altitude_ft == 9000.0


def test_a_hold_with_only_a_ceiling_uses_it() -> None:
    ceiling_only = NORTH_HOLD.model_copy(update={"min_altitude_ft": None})
    assert hold_placement(ceiling_only, magnetic_variation_deg=NO_VARIATION).altitude_ft == 10_000.0


def test_a_hold_with_no_published_altitude_refuses_to_invent_one() -> None:
    """Sea level is not a neutral default: it is the ground, or below it."""
    no_altitude = NORTH_HOLD.model_copy(update={"min_altitude_ft": None, "max_altitude_ft": None})
    with pytest.raises(ValueError, match="publishes no altitude"):
        hold_placement(no_altitude, magnetic_variation_deg=NO_VARIATION)


def test_every_hold_placement_has_its_own_label() -> None:
    labels = {
        hold_placement(NORTH_HOLD, placement, magnetic_variation_deg=NO_VARIATION).label
        for placement in HOLD_PLACEMENTS
    }
    assert len(labels) == len(HOLD_PLACEMENTS)
    assert all(label.startswith("TOBEK hold — ") for label in labels)


def test_the_hold_placements_cover_the_racetrack() -> None:
    assert get_args(HoldPlacement) == HOLD_PLACEMENTS
    assert len(set(HOLD_PLACEMENTS)) == 4


def test_the_leg_length_comes_from_the_published_time_and_the_true_airspeed() -> None:
    """Category B holds at 135 kt indicated; at 6000 ft that is 147.7 kt true,
    and one published minute of it is 2.461 NM — not the 2.25 NM an indicated
    speed would have given."""
    tas_kt = tas_from_ias(APPROACH_CATEGORY_CIRCLING_IAS_KT["B"], 6000.0)
    assert tas_kt == pytest.approx(147.66, abs=0.01)

    placement = hold_placement(NORTH_HOLD, "hold_inbound", magnetic_variation_deg=NO_VARIATION)
    distance_nm, bearing = distance_and_bearing(FIX.position, placement.position)
    assert distance_nm == pytest.approx(2.4610, abs=1e-4)
    assert distance_nm == pytest.approx(tas_kt / 60.0, abs=1e-9)
    assert bearing == pytest.approx(180.0, abs=1e-9)


def test_the_racetrack_width_is_two_turn_radii() -> None:
    """The 180° at each end is a half-circle whose diameter is the width."""
    tas_kt = tas_from_ias(APPROACH_CATEGORY_CIRCLING_IAS_KT["B"], 6000.0)
    expected_width_nm = 2.0 * turn_radius_nm(tas_kt)
    assert expected_width_nm == pytest.approx(1.5667, abs=1e-4)

    outbound = hold_placement(NORTH_HOLD, "hold_outbound", magnetic_variation_deg=NO_VARIATION)
    width_nm, bearing = distance_and_bearing(FIX.position, outbound.position)
    assert width_nm == pytest.approx(expected_width_nm, abs=1e-9)
    assert bearing == pytest.approx(90.0, abs=1e-9)


def test_a_heavier_category_flies_a_bigger_racetrack() -> None:
    """Nothing about the pattern is fixed by the chart alone: a category D
    aircraft needs a longer leg and a wider turn at the same fix."""
    light = hold_placement(
        NORTH_HOLD, "hold_outbound_end", magnetic_variation_deg=NO_VARIATION, category="A"
    )
    heavy = hold_placement(
        NORTH_HOLD, "hold_outbound_end", magnetic_variation_deg=NO_VARIATION, category="D"
    )
    light_nm, _ = distance_and_bearing(FIX.position, light.position)
    heavy_nm, _ = distance_and_bearing(FIX.position, heavy.position)
    assert heavy_nm > light_nm


def test_an_explicit_leg_length_overrides_the_published_time() -> None:
    placement = hold_placement(
        NORTH_HOLD, "hold_inbound", magnetic_variation_deg=NO_VARIATION, leg_length_nm=5.0
    )
    distance_nm, _ = distance_and_bearing(FIX.position, placement.position)
    assert distance_nm == pytest.approx(5.0, abs=1e-6)


def test_the_variation_rotates_the_whole_pattern() -> None:
    """10°E variation on a 0° magnetic inbound course: the leg lies on 190° true,
    not 180°. Defaulting the variation to zero would be a mile of error at the
    end of a 6 NM leg."""
    placement = hold_placement(NORTH_HOLD, "hold_inbound", magnetic_variation_deg=10.0)
    _, bearing = distance_and_bearing(FIX.position, placement.position)
    assert bearing == pytest.approx(190.0, abs=1e-6)
    assert placement.heading_deg == pytest.approx(10.0)


def test_a_hold_is_flown_at_a_manoeuvring_speed() -> None:
    assert hold_placement(NORTH_HOLD, magnetic_variation_deg=NO_VARIATION).ias_kt == 135.0
    assert (
        hold_placement(NORTH_HOLD, magnetic_variation_deg=NO_VARIATION, category="A").ias_kt
        == 100.0
    )


def test_a_published_holding_speed_is_a_ceiling_and_not_a_target() -> None:
    """A 230 kt placard is the maximum the *procedure* allows, not the speed a
    Cessna flies it at."""
    placarded = NORTH_HOLD.model_copy(update={"speed_kt": 230.0})
    assert hold_placement(placarded, magnetic_variation_deg=NO_VARIATION, category="A").ias_kt == (
        100.0
    )
    assert hold_placement(placarded, magnetic_variation_deg=NO_VARIATION, category="E").ias_kt == (
        230.0
    )


def test_a_published_ceiling_can_never_produce_a_stall() -> None:
    """A restriction below the aircraft's own threshold speed is either bad data
    or meant for something else. Either way it does not get to slow an aeroplane
    below the speed it lands at."""
    absurd = NORTH_HOLD.model_copy(update={"speed_kt": 60.0})
    placement = hold_placement(absurd, magnetic_variation_deg=NO_VARIATION, category="B")
    assert placement.ias_kt == APPROACH_CATEGORY_VAT_KT["B"] == 120.0


def test_an_explicit_speed_beats_the_placard_and_the_category() -> None:
    placarded = NORTH_HOLD.model_copy(update={"speed_kt": 230.0})
    placement = hold_placement(
        placarded, magnetic_variation_deg=NO_VARIATION, category="A", ias_kt=175.0
    )
    assert placement.ias_kt == 175.0


def test_no_hold_placement_is_ever_stationary() -> None:
    for placement in HOLD_PLACEMENTS:
        assert hold_placement(NORTH_HOLD, placement, magnetic_variation_deg=NO_VARIATION).ias_kt > (
            0.0
        )


# --------------------------------------------------------------------------
# Hold entries
# --------------------------------------------------------------------------


def test_an_entry_placement_sits_before_the_fix_on_the_arrival_course() -> None:
    """Arriving from the west on 090°: three miles west of the fix, tracking it.

    The heading at the placement is *not* 090° and must not be asserted as such.
    The requested arrival course is the course over the **fix**, and along an
    east-west geodesic the true heading grows by the convergence of the
    meridians on the way: 0.042° over these 3 NM at 40°N. What the placement
    guarantees is the arrival, so that is what is checked here — exactly, rather
    than the departure heading approximately.
    """
    placement = hold_entry_placement(NORTH_HOLD, 90.0, magnetic_variation_deg=NO_VARIATION)
    distance_nm, bearing = distance_and_bearing(FIX.position, placement.position)
    assert distance_nm == pytest.approx(DEFAULT_HOLD_ENTRY_DISTANCE_NM, abs=1e-6)
    assert bearing == pytest.approx(270.0, abs=1e-6)
    arrival_deg = Geodesic.WGS84.Inverse(
        placement.position.latitude,
        placement.position.longitude,
        FIX.position.latitude,
        FIX.position.longitude,
    )["azi2"]
    assert arrival_deg == pytest.approx(90.0, abs=1e-9)
    assert placement.heading_deg == pytest.approx(90.0 - 0.042, abs=0.001)
    assert placement.altitude_ft == 6000.0


def test_the_entry_placement_actually_points_at_the_fix() -> None:
    """The heading is the exact geodesic course to the fix, not the requested
    one: over 3 NM the two differ only by the convergence, but they do differ."""
    placement = hold_entry_placement(NORTH_HOLD, 130.0, magnetic_variation_deg=NO_VARIATION)
    _, course_to_fix = distance_and_bearing(placement.position, FIX.position)
    assert placement.heading_deg == pytest.approx(course_to_fix, abs=1e-12)


@pytest.mark.parametrize(
    ("arrival_deg", "entry"), [(90.0, "direct"), (220.0, "parallel"), (320.0, "teardrop")]
)
def test_the_entry_placement_names_the_entry_it_sets_up(arrival_deg: float, entry: str) -> None:
    placement = hold_entry_placement(NORTH_HOLD, arrival_deg, magnetic_variation_deg=NO_VARIATION)
    assert placement.label == f"TOBEK hold — {entry} entry"


def test_the_entry_placement_honours_the_variation() -> None:
    """Same arrival course, same published hold, different local variation: a
    parallel entry becomes a direct one, and the label has to follow."""
    parallel = hold_entry_placement(NORTH_HOLD, 200.0, magnetic_variation_deg=0.0)
    direct = hold_entry_placement(NORTH_HOLD, 200.0, magnetic_variation_deg=30.0)
    assert parallel.label.endswith("parallel entry")
    assert direct.label.endswith("direct entry")


def test_the_entry_distance_is_adjustable() -> None:
    placement = hold_entry_placement(
        NORTH_HOLD, 180.0, magnetic_variation_deg=NO_VARIATION, distance_nm=8.0
    )
    distance_nm, bearing = distance_and_bearing(FIX.position, placement.position)
    assert distance_nm == pytest.approx(8.0, abs=1e-6)
    assert bearing == pytest.approx(0.0, abs=1e-6)


def test_an_entry_placement_is_flying() -> None:
    placement = hold_entry_placement(NORTH_HOLD, 90.0, magnetic_variation_deg=NO_VARIATION)
    assert placement.ias_kt == 135.0
    assert placement.to_setup().ias_kt == 135.0
    assert placement.to_setup().altitude_ft == 6000.0


def test_an_entry_into_a_hold_with_no_altitude_is_refused() -> None:
    no_altitude = NORTH_HOLD.model_copy(update={"min_altitude_ft": None, "max_altitude_ft": None})
    with pytest.raises(ValueError, match="publishes no altitude"):
        hold_entry_placement(no_altitude, 90.0, magnetic_variation_deg=NO_VARIATION)


# --------------------------------------------------------------------------
# Procedure legs
# --------------------------------------------------------------------------


GOXOL = Waypoint(
    ident="GOXOL", kind="fix", position=GeoPosition(latitude=40.0, longitude=-3.0), region_code="LE"
)
ELVAR = Waypoint(
    ident="ELVAR", kind="fix", position=GeoPosition(latitude=40.5, longitude=-3.0), region_code="LE"
)
MD800 = Waypoint(
    ident="MD800", kind="fix", position=GeoPosition(latitude=41.0, longitude=-3.0), region_code="LE"
)

IAF_LEG = ProcedureLeg(
    sequence=10,
    path_terminator="IF",
    is_positionable=True,
    fix=GOXOL,
    altitude=AltitudeConstraint(descriptor="+", min_ft=5000.0),
    is_initial_approach_fix=True,
)

FAF_LEG = ProcedureLeg(
    sequence=20,
    path_terminator="CF",
    is_positionable=True,
    fix=ELVAR,
    altitude=AltitudeConstraint(descriptor="@", min_ft=3000.0, max_ft=3000.0),
    speed=SpeedConstraint(descriptor="-", max_kt=180.0),
    is_final_approach_fix=True,
)

CLIMB_LEG = ProcedureLeg(
    sequence=30,
    path_terminator="CA",
    is_positionable=False,
    unpositionable_reason="a CA leg ends at an altitude, not at a fix",
    is_missed_approach_leg=True,
)

UNRESTRICTED_LEG = ProcedureLeg(
    sequence=40,
    path_terminator="TF",
    is_positionable=True,
    fix=MD800,
    is_end_of_procedure=True,
)

APPROACH = Procedure(
    airport_icao="LEMD",
    kind="approach",
    ident="I32L",
    transition="ADUXO",
    runway_idents=("32L",),
    approach_type="ils",
    legs=(IAF_LEG, FAF_LEG, CLIMB_LEG, UNRESTRICTED_LEG),
)


def test_only_the_legs_with_a_resolved_fix_are_offered() -> None:
    assert positionable_legs(APPROACH) == (IAF_LEG, FAF_LEG, UNRESTRICTED_LEG)


def test_an_unpositionable_leg_is_still_part_of_the_procedure() -> None:
    """It is displayed — an instructor reading the missed approach needs it —
    but it is not offered as a position."""
    assert CLIMB_LEG in APPROACH.legs
    assert CLIMB_LEG not in positionable_legs(APPROACH)


def test_a_leg_placement_sits_over_its_fix() -> None:
    placement = procedure_leg_placement(FAF_LEG)
    assert placement.position.latitude == pytest.approx(ELVAR.position.latitude, abs=1e-12)
    assert placement.position.longitude == pytest.approx(ELVAR.position.longitude, abs=1e-12)


def test_a_leg_placement_takes_the_published_altitude() -> None:
    assert procedure_leg_placement(FAF_LEG).altitude_ft == 3000.0
    assert procedure_leg_placement(IAF_LEG).altitude_ft == 5000.0


def test_an_altitude_band_places_at_its_floor() -> None:
    """The rule AltitudeConstraint.suggested_ft states, applied here: an
    aircraft entering a FL140/10000 window from above levels at 10 000."""
    banded = FAF_LEG.model_copy(
        update={
            "altitude": AltitudeConstraint(
                descriptor="B", min_ft=10_000.0, max_ft=14_000.0, max_is_flight_level=True
            )
        }
    )
    assert procedure_leg_placement(banded).altitude_ft == 10_000.0


def test_an_explicit_altitude_beats_the_chart() -> None:
    assert procedure_leg_placement(FAF_LEG, altitude_ft=4500.0).altitude_ft == 4500.0


def test_a_leg_with_no_published_altitude_refuses_to_invent_one() -> None:
    with pytest.raises(ValueError, match="publishes no altitude constraint"):
        procedure_leg_placement(UNRESTRICTED_LEG)
    assert procedure_leg_placement(UNRESTRICTED_LEG, altitude_ft=7000.0).altitude_ft == 7000.0


def test_an_unpositionable_leg_is_refused_with_the_published_reason() -> None:
    """The UI greys these out; reaching this function anyway is a bug, and the
    message says which of the two failures it was."""
    with pytest.raises(ValueError, match="a CA leg ends at an altitude, not at a fix"):
        procedure_leg_placement(CLIMB_LEG)


def test_a_leg_whose_fix_never_resolved_is_refused_too() -> None:
    unresolved = ProcedureLeg(
        sequence=50,
        path_terminator="TF",
        is_positionable=False,
        unpositionable_reason="fix ABCDE (LE/P/C) is not in the index",
        fix=None,
    )
    with pytest.raises(ValueError, match="not in the index"):
        procedure_leg_placement(unresolved)


def test_a_leg_speed_restriction_is_a_ceiling_and_not_a_target() -> None:
    """180 kt on the FAF leg: a category D jet slows to it, a trainer ignores it.

    A trainer is nowhere near the placard and keeps its own circling speed; a
    category D aircraft would fly 205 and is held down to the published 180.
    Category E is *not* the example here: its threshold speed is 210 kt, above
    the placard, so the stall floor wins instead — see the test below.
    """
    assert procedure_leg_placement(FAF_LEG, category="D").ias_kt == 180.0
    assert procedure_leg_placement(FAF_LEG, category="A").ias_kt == 100.0
    assert procedure_leg_placement(FAF_LEG).ias_kt == 135.0


def test_a_leg_ceiling_below_the_category_threshold_speed_loses_to_it() -> None:
    """The published 180 kt is below a category E aircraft's 210 kt threshold
    speed, and flying the placard would put it under its own approach speed.
    The floor is the whole point of issue #39: too fast is a fast approach,
    too slow is a stall."""
    assert procedure_leg_placement(FAF_LEG, category="E").ias_kt == APPROACH_CATEGORY_VAT_KT["E"]


def test_a_leg_minimum_speed_is_respected() -> None:
    fast = FAF_LEG.model_copy(update={"speed": SpeedConstraint(descriptor="+", min_kt=210.0)})
    assert procedure_leg_placement(fast, category="A").ias_kt == 210.0


def test_a_leg_speed_restriction_can_never_produce_a_stall() -> None:
    absurd = FAF_LEG.model_copy(update={"speed": SpeedConstraint(descriptor="-", max_kt=45.0)})
    assert procedure_leg_placement(absurd, category="B").ias_kt == APPROACH_CATEGORY_VAT_KT["B"]


def test_an_explicit_leg_speed_beats_the_restriction() -> None:
    assert procedure_leg_placement(FAF_LEG, ias_kt=250.0, category="A").ias_kt == 250.0


def test_a_leg_heading_comes_from_the_geometry_not_from_the_chart() -> None:
    """A published outbound course is magnetic, so it is never used as a
    heading. The bearing to the next fix is: ELVAR to MD800 is due north."""
    assert procedure_leg_placement(FAF_LEG, next_fix=MD800).heading_deg == pytest.approx(
        0.0, abs=1e-9
    )
    assert procedure_leg_placement(FAF_LEG, previous_fix=GOXOL).heading_deg == pytest.approx(
        0.0, abs=1e-9
    )
    assert procedure_leg_placement(FAF_LEG, heading_deg=-90.0).heading_deg == pytest.approx(270.0)
    assert procedure_leg_placement(FAF_LEG).heading_deg == 0.0


def test_a_leg_heading_keeps_the_inbound_course_over_a_long_previous_leg() -> None:
    """The arrival bearing, not the departure one: over 10° of longitude at 40°
    latitude the two differ by 6.4°, and only one of them is the direction the
    aircraft is actually pointing when it gets there."""
    far_west = Waypoint(
        ident="WEST", kind="fix", position=GeoPosition(latitude=40.5, longitude=-13.0)
    )
    placement = procedure_leg_placement(FAF_LEG, previous_fix=far_west)
    _, departure_bearing = distance_and_bearing(far_west.position, ELVAR.position)
    assert placement.heading_deg == pytest.approx(180.0 - departure_bearing, abs=1e-9)
    assert placement.heading_deg > 90.0


def test_every_navdata_placement_is_airborne() -> None:
    """Holds, hold entries and procedure legs are flown by construction, so
    their profile is ``"airborne"``: gear up, clean, level, cruise power. None
    of them is a final — a final knows its glideslope and its ILS, and nothing
    here does (#8)."""
    assert hold_placement(NORTH_HOLD, magnetic_variation_deg=NO_VARIATION).profile == "airborne"
    assert (
        hold_entry_placement(NORTH_HOLD, 90.0, magnetic_variation_deg=NO_VARIATION).profile
        == "airborne"
    )
    assert procedure_leg_placement(FAF_LEG).profile == "airborne"


def test_a_leg_label_names_the_fix_and_its_role() -> None:
    assert procedure_leg_placement(FAF_LEG).label == "over ELVAR (FAF)"
    assert procedure_leg_placement(IAF_LEG).label == "over GOXOL (IAF)"
    assert procedure_leg_placement(UNRESTRICTED_LEG, altitude_ft=7000.0).label == "over MD800"
    assert procedure_leg_placement(FAF_LEG, procedure_ident="I32L").label == "I32L at ELVAR (FAF)"


def test_a_missed_approach_point_is_labelled_as_one() -> None:
    map_leg = FAF_LEG.model_copy(
        update={"is_final_approach_fix": False, "is_missed_approach_point": True}
    )
    assert procedure_leg_placement(map_leg).label == "over ELVAR (MAP)"


# --------------------------------------------------------------------------
# Whole procedures
# --------------------------------------------------------------------------


def test_a_procedure_placement_finds_the_leg_by_its_published_sequence() -> None:
    """Sequence 20, not index 1 — the source numbers legs 10, 20, 30."""
    placement = procedure_placement(APPROACH, 20)
    assert placement.position.latitude == pytest.approx(ELVAR.position.latitude, abs=1e-12)
    assert placement.altitude_ft == 3000.0
    assert placement.label == "I32L.ADUXO at ELVAR (FAF)"


def test_a_procedure_placement_orients_itself_from_the_next_fix() -> None:
    placement = procedure_placement(APPROACH, 10)
    _, bearing = distance_and_bearing(GOXOL.position, ELVAR.position)
    assert placement.heading_deg == pytest.approx(bearing, abs=1e-12)


def test_a_climb_leg_between_two_fixes_does_not_break_the_orientation() -> None:
    """Sequence 20's next *positionable* fix is 40: the CA leg in between has no
    coordinate, but the aircraft still has to be pointing somewhere sensible."""
    placement = procedure_placement(APPROACH, 20)
    _, bearing = distance_and_bearing(ELVAR.position, MD800.position)
    assert placement.heading_deg == pytest.approx(bearing, abs=1e-12)


def test_the_last_leg_falls_back_to_the_previous_fix() -> None:
    placement = procedure_placement(APPROACH, 40, altitude_ft=8000.0)
    assert placement.heading_deg == pytest.approx(0.0, abs=1e-9)


def test_an_unknown_sequence_says_which_ones_exist() -> None:
    with pytest.raises(ValueError, match="10, 20, 30, 40"):
        procedure_placement(APPROACH, 25)


def test_a_procedure_without_a_transition_is_labelled_by_its_ident_alone() -> None:
    common = APPROACH.model_copy(update={"transition": None})
    assert procedure_placement(common, 20).label == "I32L at ELVAR (FAF)"


def test_a_procedure_placement_forwards_the_speed_and_the_category() -> None:
    """Same resolution as the leg placement it delegates to: category D is held
    down to the leg's published 180 kt, and an explicit speed beats everything."""
    assert procedure_placement(APPROACH, 20, category="D").ias_kt == 180.0
    assert procedure_placement(APPROACH, 20, ias_kt=99.0).ias_kt == 99.0


def test_a_procedure_placement_is_never_stationary() -> None:
    for leg in positionable_legs(APPROACH):
        placement = procedure_placement(APPROACH, leg.sequence, altitude_ft=6000.0)
        assert placement.ias_kt >= APPROACH_CATEGORY_VAT_KT["A"]


# --------------------------------------------------------------------------
# A navdata waypoint is a placement anchor in its own right
# --------------------------------------------------------------------------


def test_a_navdata_waypoint_can_be_placed_over_directly() -> None:
    placement = waypoint_placement(GOXOL, 7000.0)
    assert placement.position.latitude == pytest.approx(GOXOL.position.latitude, abs=1e-12)
    assert placement.altitude_ft == 7000.0
    assert placement.label == "over GOXOL"


def test_an_explicit_ident_still_wins() -> None:
    assert waypoint_placement(GOXOL, 7000.0, ident="the initial fix").label == (
        "over the initial fix"
    )


def test_a_bare_point_keeps_its_generic_label() -> None:
    assert waypoint_placement(GeoPosition(latitude=40.0, longitude=-3.0), 7000.0).label == (
        "over waypoint"
    )


def test_the_neighbouring_fixes_may_be_waypoints_too() -> None:
    from_waypoint = waypoint_placement(GOXOL, 7000.0, next_fix=ELVAR)
    from_point = waypoint_placement(GOXOL.position, 7000.0, next_fix=ELVAR.position)
    assert from_waypoint.heading_deg == pytest.approx(from_point.heading_deg, abs=1e-12)
    assert from_waypoint.heading_deg == pytest.approx(0.0, abs=1e-9)


def test_a_waypoint_placement_matches_the_underlying_primitive() -> None:
    """Fifteen miles north-east of the fix at 7000 ft, placed by coordinate."""
    elsewhere = point_at_distance_and_bearing(GOXOL.position, 15.0, 45.0)
    placement = waypoint_placement(elsewhere, 7000.0)
    distance_nm, bearing = distance_and_bearing(GOXOL.position, placement.position)
    assert distance_nm == pytest.approx(15.0, abs=1e-6)
    assert bearing == pytest.approx(45.0, abs=1e-6)


# --------------------------------------------------------------------------
# The import direction that makes all of the above legal
# --------------------------------------------------------------------------


def test_the_navdata_models_do_not_import_back_into_the_geodesy() -> None:
    """``core/geodesy.py`` imports ``core/navdata/models.py``, which is only
    safe while that file imports nothing from ``core.geodesy``.

    ``core/navdata/`` as a whole *does* depend on this module — the indexer
    measures distances with it — so if the models started importing it back, the
    two would close a cycle and every later contributor would be paying for it
    with ``TYPE_CHECKING`` guards. Asserted by parsing rather than importing, so
    a violation is reported here instead of as an ImportError somewhere else.
    """
    models = Path(__file__).resolve().parents[2] / "core" / "navdata" / "models.py"
    tree = ast.parse(models.read_text(encoding="utf-8"), filename=str(models))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    offenders = sorted(name for name in imported if name.startswith("core.geodesy"))
    assert not offenders, (
        f"core/navdata/models.py imports {offenders}, which closes a cycle with core/geodesy.py. "
        "The navdata models are data: they depend on core/models.py and nothing else."
    )
