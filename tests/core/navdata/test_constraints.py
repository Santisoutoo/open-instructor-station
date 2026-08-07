"""The constraint rules, stated once on the model and pinned once here.

``suggested_ft`` is the rule the Position Manager places an aircraft with, so it
lives on the model rather than in the caller: stated once, tested once, and
identical in the UI preview and in the actual placement.

The band case is the one that matters. An aircraft on a STAR enters a window
from above and the crew targets the **bottom** of it; placing at the top of a
``FL140`` / ``10000`` window puts the aircraft 4000 ft high on a descent profile
it then cannot fly.
"""

from __future__ import annotations

import pytest

from core.navdata.models import AltitudeConstraint, SpeedConstraint


class TestAltitudeSuggestion:
    def test_at_or_above_suggests_the_floor(self) -> None:
        """Source form: ``+,02400``."""
        constraint = AltitudeConstraint(descriptor="+", min_ft=2400.0)
        assert constraint.suggested_ft == 2400.0

    def test_at_or_below_suggests_the_ceiling(self) -> None:
        """Source form: ``-,05000``."""
        constraint = AltitudeConstraint(descriptor="-", max_ft=5000.0)
        assert constraint.suggested_ft == 5000.0

    def test_a_band_suggests_its_lower_bound(self) -> None:
        """Source form: ``B,FL140,10000``. The top of the window is 4000 ft wrong."""
        constraint = AltitudeConstraint(
            descriptor="B", min_ft=10_000.0, max_ft=14_000.0, max_is_flight_level=True
        )
        assert constraint.suggested_ft == 10_000.0

    def test_an_exact_altitude_suggests_itself(self) -> None:
        """Source form: ``J,05500,05500`` — a glideslope intercept."""
        constraint = AltitudeConstraint(descriptor="J", min_ft=5500.0, max_ft=5500.0)
        assert constraint.suggested_ft == 5500.0

    def test_an_empty_constraint_suggests_nothing(self) -> None:
        assert AltitudeConstraint(descriptor="").suggested_ft is None


class TestAltitudeDisplay:
    """Flight levels are stored in feet with a flag, so the published form survives."""

    def test_a_flight_level_renders_as_published(self) -> None:
        constraint = AltitudeConstraint(descriptor="+", min_ft=24_500.0, min_is_flight_level=True)
        assert constraint.display == "at or above FL245"

    def test_a_band_renders_both_bounds_in_their_own_form(self) -> None:
        constraint = AltitudeConstraint(
            descriptor="B", min_ft=10_000.0, max_ft=14_000.0, max_is_flight_level=True
        )
        assert constraint.display == "between 10000 ft and FL140"

    def test_an_exact_altitude_renders_once(self) -> None:
        constraint = AltitudeConstraint(descriptor="J", min_ft=5500.0, max_ft=5500.0)
        assert constraint.display == "5500 ft"

    def test_at_or_below_reads_as_a_ceiling(self) -> None:
        assert AltitudeConstraint(descriptor="-", max_ft=5000.0).display == "at or below 5000 ft"

    def test_no_constraint_says_so(self) -> None:
        assert AltitudeConstraint(descriptor="").display == "unrestricted"


class TestSpeedSuggestion:
    def test_at_or_below_suggests_the_ceiling(self) -> None:
        """Source form: ``-,210`` — the common one, a terminal speed limit."""
        constraint = SpeedConstraint(descriptor="-", max_kt=210.0)
        assert constraint.suggested_kt == 210.0
        assert constraint.display == "at or below 210 kt"

    def test_at_or_above_suggests_the_floor(self) -> None:
        constraint = SpeedConstraint(descriptor="+", min_kt=160.0)
        assert constraint.suggested_kt == 160.0

    def test_the_ceiling_wins_when_both_bounds_exist(self) -> None:
        """A speed window is flown at its limit, and the limiting bound is the ceiling."""
        constraint = SpeedConstraint(descriptor="", min_kt=160.0, max_kt=210.0)
        assert constraint.suggested_kt == 210.0

    def test_an_empty_constraint_suggests_nothing(self) -> None:
        assert SpeedConstraint().suggested_kt is None
        assert SpeedConstraint().display == "unrestricted"


@pytest.mark.parametrize(
    ("value", "is_level", "expected"),
    [
        (14_000.0, True, "FL140"),
        (24_500.0, True, "FL245"),
        (5000.0, True, "FL050"),
        (10_000.0, False, "10000 ft"),
        (2400.0, False, "2400 ft"),
    ],
)
def test_flight_levels_round_trip_to_their_published_form(
    value: float, is_level: bool, expected: str
) -> None:
    constraint = AltitudeConstraint(descriptor="-", max_ft=value, max_is_flight_level=is_level)
    assert expected in constraint.display
