"""Identifier normalisation, including the transition-expansion trap.

``RW32B`` is the case worth staring at: it is not a runway, it is "both
parallels", and expanding it by assuming an L/R pair produces a wrong answer at
any airport with a centre runway. Expansion is therefore resolved against the
airport's **real** runway list, which is what these tests pin.
"""

from __future__ import annotations

import pytest

from core.navdata.normalize import (
    expand_runway_transition,
    normalize_icao,
    normalize_runway_ident,
    normalize_search_text,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("RW18L", "18L"),
        ("18L", "18L"),
        ("rw09", "09"),
        ("  32R  ", "32R"),
        ("08", "08"),  # a leading zero is how the source spells it and how a chart prints it
    ],
)
def test_runway_idents_reduce_to_the_apt_dat_form(raw: str, expected: str) -> None:
    assert normalize_runway_ident(raw) == expected


def test_icao_codes_are_upper_cased_and_stripped() -> None:
    assert normalize_icao("  lemd ") == "LEMD"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Madrid", "madrid"),
        ("Suárez", "suarez"),
        ("MÜNCHEN", "munchen"),
        ("  Köln/Bonn ", "koln/bonn"),
    ],
)
def test_search_text_is_casefolded_and_accent_stripped(raw: str, expected: str) -> None:
    """An instructor types "suarez", the data says "Suárez"."""
    assert normalize_search_text(raw) == expected


class TestTransitionExpansion:
    """The CIFP transition field is four different things wearing one costume."""

    RUNWAYS = ("32L", "32C", "32R", "14L", "14C", "14R")

    def test_an_exact_runway_expands_to_itself(self) -> None:
        assert expand_runway_transition("RW14R", self.RUNWAYS) == ("14R",)

    def test_a_parallel_group_expands_to_every_real_parallel(self) -> None:
        """RW32B at an airport with a CENTRE runway. Assuming L/R would lose 32C."""
        assert expand_runway_transition("RW32B", self.RUNWAYS) == ("32C", "32L", "32R")

    def test_a_parallel_group_expands_correctly_without_a_centre(self) -> None:
        assert expand_runway_transition("RW32B", ("32L", "32R", "18L")) == ("32L", "32R")

    def test_a_bare_number_expands_to_every_runway_with_that_number(self) -> None:
        assert expand_runway_transition("RW18", ("18L", "18R", "36L")) == ("18L", "18R")

    def test_a_bare_number_that_exists_verbatim_wins(self) -> None:
        """An airport with a single unsuffixed 18 gets 18, not a group expansion."""
        assert expand_runway_transition("RW18", ("18", "36")) == ("18",)

    @pytest.mark.parametrize("transition", ["ALL", "", "   "])
    def test_all_and_blank_mean_every_runway(self, transition: str) -> None:
        assert expand_runway_transition(transition, ("09", "27")) == ("09", "27")

    def test_a_named_transition_serves_no_specific_runway(self) -> None:
        """ADUXO is a fix, not a runway. The name is kept in `transition` instead."""
        assert expand_runway_transition("ADUXO", self.RUNWAYS) == ()

    def test_a_runway_the_airport_does_not_have_expands_to_nothing(self) -> None:
        """Never invent a runway: a placement offered on one would be unflyable."""
        assert expand_runway_transition("RW05", self.RUNWAYS) == ()
