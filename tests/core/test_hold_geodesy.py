"""Holding entries and hold placements.

The entry sectors are the part worth testing hard: they are a published,
checkable specification (ICAO Doc 8168 — a 180° direct sector, a 70° teardrop
and a 110° parallel), and getting one of the boundaries wrong produces an answer
that is plausible everywhere except within a few degrees of the edge.
"""

from __future__ import annotations

import pytest

from core.geodesy import (
    APPROACH_CATEGORY_CIRCLING_IAS_KT,
    PARALLEL_SECTOR_DEG,
    TEARDROP_SECTOR_DEG,
    HoldEntry,
    hold_entry,
    hold_leg_length_nm,
    hold_placement,
)
from core.models import GeoPosition

FIX = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=0.0)


class TestSectorWidths:
    """The three sectors must tile the compass exactly once."""

    def test_the_sectors_sum_to_a_full_circle(self) -> None:
        direct = 360.0 - TEARDROP_SECTOR_DEG - PARALLEL_SECTOR_DEG
        assert direct == 180.0

    @pytest.mark.parametrize("turn", ["L", "R"])
    def test_the_sampled_sectors_match_their_nominal_widths(self, turn: str) -> None:
        """Sampling one heading per degree reproduces the published widths.

        Within one sample, not exactly: the sectors are half-open, so a boundary
        degree lands in one neighbour and not the other and the integer counts
        come out a degree either side of the nominal width. Which side each
        boundary falls on is asserted explicitly below, where it is readable.
        """
        counts: dict[HoldEntry, int] = {"direct": 0, "parallel": 0, "teardrop": 0}
        for heading in range(360):
            counts[hold_entry(0.0, float(heading), turn)] += 1  # type: ignore[arg-type]

        assert sum(counts.values()) == 360
        assert counts["direct"] == pytest.approx(180.0, abs=1)
        assert counts["teardrop"] == pytest.approx(TEARDROP_SECTOR_DEG, abs=1)
        assert counts["parallel"] == pytest.approx(PARALLEL_SECTOR_DEG, abs=1)


class TestRightHandEntries:
    """Standard pattern: holding side to the right of the inbound course."""

    @pytest.mark.parametrize(
        ("relative_deg", "expected"),
        [
            (0.0, "direct"),  # established on the inbound course
            (90.0, "direct"),  # turning right onto outbound: a 90° turn
            (110.0, "direct"),  # last degree of the direct sector
            (110.1, "teardrop"),
            (145.0, "teardrop"),
            (180.0, "teardrop"),  # flying outbound; boundary, teardrop by convention
            (180.1, "parallel"),
            (270.0, "parallel"),
            (289.9, "parallel"),
            (290.0, "direct"),  # parallel sector closes
            (359.0, "direct"),
        ],
    )
    def test_sector(self, relative_deg: float, expected: HoldEntry) -> None:
        assert hold_entry(0.0, relative_deg, "R") == expected

    def test_the_inbound_course_is_the_origin_not_north(self) -> None:
        # The same geometry rotated 250°: only the relative angle matters.
        assert hold_entry(250.0, 250.0, "R") == "direct"
        assert hold_entry(250.0, (250.0 + 145.0) % 360.0, "R") == "teardrop"
        assert hold_entry(250.0, (250.0 + 270.0) % 360.0, "R") == "parallel"


class TestLeftHandIsTheMirror:
    """A left-hand hold is the right-hand one reflected about the inbound course."""

    @pytest.mark.parametrize("relative_deg", [0.0, 45.0, 110.0, 145.0, 180.0, 250.0, 300.0])
    def test_mirror(self, relative_deg: float) -> None:
        mirrored = (360.0 - relative_deg) % 360.0
        assert hold_entry(0.0, relative_deg, "L") == hold_entry(0.0, mirrored, "R")

    def test_the_holding_side_actually_swaps(self) -> None:
        # 270° relative is parallel in a right-hand hold and direct in a left one.
        assert hold_entry(0.0, 270.0, "R") == "parallel"
        assert hold_entry(0.0, 270.0, "L") == "direct"


class TestLegLength:
    def test_a_published_distance_wins(self) -> None:
        assert hold_leg_length_nm(210.0, leg_length_nm=7.0, leg_time_min=1.0) == 7.0

    def test_a_published_time_becomes_a_distance_at_the_flown_speed(self) -> None:
        # One minute at 180 kt is 3 NM.
        assert hold_leg_length_nm(180.0, leg_time_min=1.0) == pytest.approx(3.0)

    def test_nothing_published_stays_nothing(self) -> None:
        """No ICAO one-minute default: a guessed racetrack drawn like a published
        one is a lie the instructor cannot see through."""
        assert hold_leg_length_nm(180.0) is None


class TestHoldPlacement:
    def test_it_sits_over_the_fix_on_the_inbound_course(self) -> None:
        placement = hold_placement(FIX, 123.0, "R", 8000.0, ident="GOXOL")
        assert placement.position.latitude == pytest.approx(FIX.latitude)
        assert placement.position.longitude == pytest.approx(FIX.longitude)
        assert placement.position.altitude_ft == 8000.0
        assert placement.heading_deg == pytest.approx(123.0)
        assert "GOXOL" in placement.label
        assert "right-hand" in placement.label

    def test_the_fixs_own_altitude_is_ignored(self) -> None:
        fix = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=99.0)
        assert hold_placement(fix, 0.0, "R", 5000.0).position.altitude_ft == 5000.0

    def test_a_hold_is_never_placed_at_zero_knots(self) -> None:
        placement = hold_placement(FIX, 0.0, "L", 6000.0)
        assert placement.ias_kt == APPROACH_CATEGORY_CIRCLING_IAS_KT["B"]
        assert placement.ias_kt > 0.0

    def test_an_explicit_speed_wins_over_the_category(self) -> None:
        placement = hold_placement(FIX, 0.0, "R", 6000.0, ias_kt=210.0, category="A")
        assert placement.ias_kt == 210.0

    def test_the_heading_is_normalised(self) -> None:
        assert hold_placement(FIX, 400.0, "R", 6000.0).heading_deg == pytest.approx(40.0)
