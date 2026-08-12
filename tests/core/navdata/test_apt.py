"""The ``apt.dat`` reader, against the committed hand-written fixture tree.

This is the parser most likely to break and the one CI can genuinely cover: a
simulator cannot be installed on a GitHub runner, but a few kilobytes of
invented ``apt.dat`` can be committed. Every airport, runway and stand asserted
on below is fabricated — ``ZZZZ`` and ``ZZZY`` are in the ICAO "no location"
block — and the coordinates are round numbers so the expected geometry is
checkable by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.models import GeoPosition
from core.navdata.xplane_native.apt import (
    INTERESTING_PREFIXES,
    ParsedAirport,
    iter_airports,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "navdata" / "xp_root"
APT_DAT = FIXTURE_ROOT / "Global Scenery" / "Global Airports" / "Earth nav data" / "apt.dat"


@pytest.fixture(scope="module")
def parsed() -> tuple[list[ParsedAirport], list[str]]:
    """Every airport in the fixture, plus the reasons anything was skipped."""
    skipped: list[str] = []
    with APT_DAT.open(encoding="utf-8") as handle:
        airports = list(iter_airports(handle, on_skip=lambda reason, _line: skipped.append(reason)))
    return airports, skipped


def _airport(parsed: tuple[list[ParsedAirport], list[str]], icao: str) -> ParsedAirport:
    return next(a for a in parsed[0] if a.icao == icao)


# --------------------------------------------------------------------------
# The prefix filter — the one required optimisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "110 1 0.25 0.0 taxiway pavement header",
        "111 40.00000000 -3.00000000",
        "112 40.00000000 -3.00000000 40.1 -3.1",
        "120 a linear feature",
        "130 an airport boundary",
        "101 60.96 0 16 40.0 -3.0 34 40.1 -3.1",
        "102 H1 40.0 -3.0 2.0 15.0 15.0 2 0 0.25 0",
    ],
)
def test_geometry_and_out_of_scope_rows_never_reach_the_parser(line: str) -> None:
    """90% of a real ``apt.dat`` is taxiway geometry, and it is rejected on the raw line.

    Rejecting these with a ``startswith`` on the untouched string, before any
    ``split()``, is the difference between a one-minute index build and a
    five-minute one. Water runways (``101``) and helipads (``102``) are rejected
    for a different reason — they are out of scope for Phase 1 — but the same
    test covers both, because the filter is the only thing standing between
    either of them and the runway table.
    """
    assert not line.startswith(INTERESTING_PREFIXES)


@pytest.mark.parametrize(
    "line",
    ["1 2000 1 0 ZZZZ Name", "100 45 1 0", "1300 40 -3 0 gate all X", "1302 city Nowhere"],
)
def test_the_rows_that_matter_do_reach_the_parser(line: str) -> None:
    assert line.startswith(INTERESTING_PREFIXES)


# --------------------------------------------------------------------------
# Airports
# --------------------------------------------------------------------------


def test_only_land_airports_are_indexed(parsed: tuple[list[ParsedAirport], list[str]]) -> None:
    """A heliport header (``17``) is recognised so it can be *excluded*."""
    assert [a.icao for a in parsed[0]] == ["ZZZZ", "ZZZY"]


def test_airport_metadata_comes_from_the_1302_rows(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    airport = _airport(parsed, "ZZZZ")
    assert airport.name == "Zulu Fictional"
    assert airport.iata == "ZZZ"
    assert airport.city == "Nowhere"
    assert airport.country == "Neverland"
    assert airport.region_code == "LE"
    assert airport.elevation_ft == pytest.approx(2000.0)
    assert airport.transition_altitude_ft == 6000


def test_a_transition_level_published_as_a_flight_level_becomes_feet(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """``FL70`` is 7000 ft. Keeping it as a string would push the conversion into every caller."""
    assert _airport(parsed, "ZZZZ").transition_level_ft == 7000


def test_the_reference_point_is_the_published_datum(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    airport = _airport(parsed, "ZZZZ")
    assert airport.latitude == pytest.approx(40.0)
    assert airport.longitude == pytest.approx(-3.0)


def test_an_airport_without_a_datum_falls_back_to_its_pavement() -> None:
    """A missing datum is not a missing airport: it is still searchable from its own runway."""
    lines = [
        "1 100 0 0 ZZZX No Datum Field\n",
        "100 30.00 1 0 0.00 1 2 1 09 10.00000000 20.00000000 0.00 0.00 1 0 0 1 "
        "27 10.00000000 20.01000000 0.00 0.00 1 0 0 1\n",
    ]
    airport = next(iter(iter_airports(lines)))
    assert airport.latitude == pytest.approx(10.0)
    assert airport.longitude == pytest.approx(20.005, abs=1e-6)


def test_an_airport_with_no_position_at_all_is_skipped_and_counted() -> None:
    """Indexing a coordinate-less airport would only produce a row that fails later."""
    skipped: list[str] = []
    airports = list(
        iter_airports(
            ["1 100 0 0 ZZZW Nowhere At All\n"],
            on_skip=lambda reason, _line: skipped.append(reason),
        )
    )
    assert airports == []
    assert len(skipped) == 1


def test_the_legacy_tower_flag_is_read(parsed: tuple[list[ParsedAirport], list[str]]) -> None:
    assert _airport(parsed, "ZZZZ").has_tower is True
    assert _airport(parsed, "ZZZY").has_tower is False


# --------------------------------------------------------------------------
# Runways
# --------------------------------------------------------------------------


def test_a_runway_row_produces_two_ends(parsed: tuple[list[ParsedAirport], list[str]]) -> None:
    """A placement is always relative to one end, so 09 and 27 are two objects."""
    airport = _airport(parsed, "ZZZZ")
    assert {r.ident for r in airport.runways} == {"09", "27"}
    assert airport.runway_count == 2
    ends = {r.ident: r for r in airport.runways}
    assert ends["09"].opposite_ident == "27"
    assert ends["27"].opposite_ident == "09"


def test_the_bearing_is_geodesic_and_the_two_ends_are_reciprocal(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """The bearing is computed from the coordinates, never from a published course."""
    ends = {r.ident: r for r in _airport(parsed, "ZZZZ").runways}
    expected = distance_and_bearing(
        GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=0.0),
        GeoPosition(latitude=40.0, longitude=-2.9648, altitude_ft=0.0),
    )[1]
    assert ends["09"].true_bearing_deg == pytest.approx(expected)
    assert ends["09"].true_bearing_deg == pytest.approx(89.9887, abs=1e-3)
    assert ends["27"].true_bearing_deg == pytest.approx(270.0113, abs=1e-3)


def test_length_is_the_pavement_length_and_is_shared_by_both_ends(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    ends = {r.ident: r for r in _airport(parsed, "ZZZZ").runways}
    assert ends["09"].length_m == pytest.approx(ends["27"].length_m)
    assert ends["09"].length_m == pytest.approx(3005.86, abs=0.05)


def test_an_undisplaced_threshold_is_the_published_coordinate_untouched(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """Bit-for-bit, not a geodesic round trip: 40 00 00 N 003 00 00 W stays exactly that."""
    end = next(r for r in _airport(parsed, "ZZZZ").runways if r.ident == "09")
    assert end.displaced_threshold_m == 0.0
    assert end.threshold_lat == 40.0
    assert end.threshold_lon == -3.0
    assert (end.threshold_lat, end.threshold_lon) == (end.end_lat, end.end_lon)


def test_a_displaced_threshold_is_walked_forward_along_the_runway_axis(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """``apt.dat`` publishes the pavement end; the landing threshold is down the runway.

    At LEMD 18L those two points are ~496 m apart, which is 0.27 NM of error on
    a 10 NM final before anything else goes wrong. This asserts the walk in both
    of its parts: the distance is the published displacement, and the direction
    is the runway's own bearing.
    """
    end = next(r for r in _airport(parsed, "ZZZY").runways if r.ident == "18")
    assert end.displaced_threshold_m == pytest.approx(300.0)

    walked_nm, walked_bearing = distance_and_bearing(
        GeoPosition(latitude=end.end_lat, longitude=end.end_lon, altitude_ft=0.0),
        GeoPosition(latitude=end.threshold_lat, longitude=end.threshold_lon, altitude_ft=0.0),
    )
    assert walked_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(300.0, abs=0.01)
    assert walked_bearing == pytest.approx(end.true_bearing_deg, abs=1e-6)


def test_the_opposite_end_of_a_displaced_runway_is_not_displaced(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """The displacement is per end. Applying 18's to 36 would move the wrong threshold."""
    end = next(r for r in _airport(parsed, "ZZZY").runways if r.ident == "36")
    assert end.displaced_threshold_m == 0.0
    assert (end.threshold_lat, end.threshold_lon) == (end.end_lat, end.end_lon)


def test_the_surface_code_is_mapped_to_the_shared_vocabulary(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    assert all(r.surface == "asphalt" for r in _airport(parsed, "ZZZZ").runways)
    assert all(r.surface == "grass" for r in _airport(parsed, "ZZZY").runways)


def test_width_is_carried(parsed: tuple[list[ParsedAirport], list[str]]) -> None:
    assert all(r.width_m == pytest.approx(45.0) for r in _airport(parsed, "ZZZZ").runways)


def test_the_longest_runway_ranks_a_search_hit(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    longest = _airport(parsed, "ZZZZ").longest_runway_m
    assert longest is not None
    assert longest == pytest.approx(3005.86, abs=0.05)


# --------------------------------------------------------------------------
# Parking
# --------------------------------------------------------------------------


def test_ramp_starts_carry_their_kind_and_heading(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    stands = {s.name: s for s in _airport(parsed, "ZZZZ").parking}
    assert set(stands) == {"R32", "GA1"}
    assert stands["R32"].kind == "gate"
    assert stands["R32"].heading_true_deg == pytest.approx(180.0)
    assert stands["GA1"].kind == "tie_down"


def test_the_1301_row_decorates_the_stand_above_it(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """``operation`` and ``airline_codes`` have no other source in the format."""
    stands = {s.name: s for s in _airport(parsed, "ZZZZ").parking}
    assert stands["R32"].operation == "airline"
    assert stands["R32"].airline_codes == "ibe baw"
    assert stands["R32"].aircraft_types == "jets|heavy"
    assert stands["GA1"].operation == "general_aviation"
    assert stands["GA1"].airline_codes is None


def test_every_parking_kind_the_format_publishes_is_covered(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    kinds = {s.kind for a in parsed[0] for s in a.parking}
    assert kinds == {"gate", "tie_down", "hangar", "misc"}


def test_a_heliports_ramp_start_does_not_attach_to_the_airport_before_it(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """This is what the ``16``/``17`` headers are recognised for."""
    names = {s.name for s in _airport(parsed, "ZZZY").parking}
    assert names == {"Hangar 1", "Remote 5"}


# --------------------------------------------------------------------------
# Malformed records
# --------------------------------------------------------------------------


def test_a_malformed_runway_row_is_skipped_and_counted(
    parsed: tuple[list[ParsedAirport], list[str]],
) -> None:
    """Real navdata always contains a few. One bad row never fails a build."""
    _, skipped = parsed
    assert len(skipped) == 1
    assert "too few fields" in skipped[0]


def test_coincident_runway_ends_are_rejected_rather_than_given_a_bearing() -> None:
    """A zero-length runway has no defensible bearing, so it is not invented."""
    skipped: list[str] = []
    lines = [
        "1 100 0 0 ZZZV Coincident Ends\n",
        "100 30.00 1 0 0.00 1 2 1 09 10.00000000 20.00000000 0.00 0.00 1 0 0 1 "
        "27 10.00000000 20.00000000 0.00 0.00 1 0 0 1\n",
        "1300 10.00000000 20.00000000 0.000 gate all Only Stand\n",
    ]
    airport = next(iter(iter_airports(lines, on_skip=lambda r, _l: skipped.append(r))))
    assert airport.runways == []
    assert skipped == ["runway ends are coincident"]
