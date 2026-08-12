"""The ``earth_*.dat`` readers and their packed-field decoders.

The decoders get golden-value tables because they are the parts of this format
that are easy to get subtly wrong and impossible to notice: a localizer bearing
that is one degree out still looks like a localizer bearing, and the aircraft
lands 300 m off the centreline before anybody asks why.

The expected values are the ones recorded in the design after being checked
against real records. **No real record is reproduced here** — only the handful
of numeric field values needed to pin a decoder, which are facts about an
encoding rather than anybody's data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.navdata.xplane_native.earth import (
    decode_packed_glideslope,
    decode_packed_localizer_bearing,
    ndb_frequency_khz,
    parse_earth_fix,
    parse_earth_hold,
    parse_earth_nav,
    tunable_radio_for,
    vhf_frequency_khz,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "navdata" / "xp_root"
CUSTOM_DATA = FIXTURE_ROOT / "Custom Data"
DEFAULT_DATA = FIXTURE_ROOT / "Resources" / "default data"


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


# --------------------------------------------------------------------------
# Packed localizer bearing — two numbers in one field
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "true_deg", "magnetic_deg"),
    [
        ("64979.763", 179.763, 180.0),
        ("116602.320", 322.320, 323.0),
        ("83392.745", 232.745, 231.0),
        ("32850.000", 90.0, 91.0),
    ],
)
def test_the_localizer_field_splits_into_a_true_and_a_magnetic_course(
    field: str, true_deg: float, magnetic_deg: float
) -> None:
    assert decode_packed_localizer_bearing(field) == (true_deg, magnetic_deg)


def test_the_split_is_integer_arithmetic_and_a_float_modulo_is_not_good_enough() -> None:
    """The obvious one-liner returns a *different number*, and this pins the difference.

    ``116602.320 % 360`` is 322.320000000007: binary rounding of the whole
    packed value leaks into the fractional degrees. Decoding the digit string
    with integer arithmetic and reattaching the fraction gives exactly 322.320,
    which is what the source published.
    """
    decoded = decode_packed_localizer_bearing("116602.320")
    assert decoded is not None
    assert decoded[0] == 322.320
    assert 116602.320 % 360 != 322.320


@pytest.mark.parametrize("field", ["", "not-a-bearing", "-1.0", "abc.def"])
def test_an_undecodable_bearing_returns_none_rather_than_raising(field: str) -> None:
    """One odd record is skipped and counted; it never fails a build."""
    assert decode_packed_localizer_bearing(field) is None


# --------------------------------------------------------------------------
# Packed glideslope — same shape, different multiplier
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "glideslope_deg", "true_deg"),
    [
        ("300179.763", 3.00, 179.763),
        ("300090.000", 3.00, 90.0),
        # A 5.5 deg approach and a 6.65 deg one: steep but real, and the values
        # no wrong multiplier reproduces.
        ("550272.500", 5.50, 272.5),
        ("665010.000", 6.65, 10.0),
        ("205260.000", 2.05, 260.0),
    ],
)
def test_the_glideslope_field_splits_into_an_angle_and_a_true_course(
    field: str, glideslope_deg: float, true_deg: float
) -> None:
    assert decode_packed_glideslope(field) == (glideslope_deg, true_deg)


def test_an_undecodable_glideslope_returns_none() -> None:
    assert decode_packed_glideslope("gibberish") is None


# --------------------------------------------------------------------------
# Frequencies — the factor-of-ten trap
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("field", "khz"), [("11150", 111_500), ("11370", 113_700)])
def test_vhf_frequencies_are_normalised_to_the_unit_aircraft_setup_uses(
    field: str, khz: int
) -> None:
    """The source stores 10 kHz units. Normalising here is what keeps the radios honest."""
    assert vhf_frequency_khz(field) == khz


def test_ndb_frequencies_are_already_in_khz() -> None:
    assert ndb_frequency_khz("380") == 380


@pytest.mark.parametrize("field", ["", "0", "-5", "n/a"])
def test_an_unusable_frequency_is_none(field: str) -> None:
    assert vhf_frequency_khz(field) is None
    assert ndb_frequency_khz(field) is None


# --------------------------------------------------------------------------
# Which radio tunes what
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "radio"),
    [
        ("vor", "nav"),
        ("vor_dme", "nav"),
        ("vortac", "nav"),
        ("dme", "nav"),
        ("tacan", "nav"),
        ("localizer", "nav"),
        ("ndb", "adf"),
        ("glideslope", None),
        ("gls", None),
    ],
)
def test_tunable_radio_distinguishes_nav_adf_and_untunable(kind: str, radio: str | None) -> None:
    """Three cases, not two: an NDB's 380 kHz does not pass ``nav1_freq_khz`` validation."""
    assert tunable_radio_for(kind) == radio  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# earth_fix.dat
# --------------------------------------------------------------------------


def test_fixes_carry_their_terminal_scope() -> None:
    """``ENRT`` becomes NULL and an airport code is kept. Collapsing this breaks SIDs."""
    fixes = list(parse_earth_fix(_lines(CUSTOM_DATA / "earth_fix.dat")))
    by_scope = {(f.ident, f.terminal_airport_icao) for f in fixes}
    assert ("ZOXOL", None) in by_scope
    assert ("ZOXOL", "ZZZZ") in by_scope


def test_the_two_records_sharing_an_ident_keep_different_coordinates() -> None:
    fixes = [
        f for f in parse_earth_fix(_lines(CUSTOM_DATA / "earth_fix.dat")) if f.ident == "ZOXOL"
    ]
    assert len(fixes) == 2
    assert {(f.latitude, f.longitude) for f in fixes} == {(40.5, -3.5), (40.2, -3.2)}


def test_the_file_header_and_terminator_are_not_records() -> None:
    """``I``, the version line and ``99`` are boilerplate, not malformed rows."""
    skipped: list[str] = []
    list(
        parse_earth_fix(
            _lines(CUSTOM_DATA / "earth_fix.dat"), on_skip=lambda r, _l: skipped.append(r)
        )
    )
    assert len(skipped) == 1
    assert "coordinate" in skipped[0]


def test_a_malformed_fix_row_is_skipped_and_counted() -> None:
    skipped: list[str] = []
    fixes = list(
        parse_earth_fix(
            ["  40.0 -3.0 GOOD ENRT LE 4530011", "  nope -3.0 BAD ENRT LE 4530011"],
            on_skip=lambda r, _l: skipped.append(r),
        )
    )
    assert [f.ident for f in fixes] == ["GOOD"]
    assert len(skipped) == 1


# --------------------------------------------------------------------------
# earth_nav.dat
# --------------------------------------------------------------------------


def test_the_vor_family_is_told_apart_by_the_published_name() -> None:
    """One row code covers VOR, VOR/DME and VORTAC; the name is where the source says which."""
    parsed = {n.ident: n for n in parse_earth_nav(_lines(CUSTOM_DATA / "earth_nav.dat"))}
    assert parsed["ZUL"].kind == "vor_dme"
    assert parsed["ZTC"].kind == "tacan"
    assert parsed["ZB"].kind == "ndb"


def test_a_terminal_row_splits_its_runway_from_its_name() -> None:
    """Field 11 is the runway for a terminal navaid and the first word of the name otherwise."""
    localizer = next(
        n for n in parse_earth_nav(_lines(CUSTOM_DATA / "earth_nav.dat")) if n.kind == "localizer"
    )
    assert localizer.airport_icao == "ZZZZ"
    assert localizer.runway_ident == "09"
    assert localizer.name == "ILS-cat-I"


def test_an_enroute_row_has_no_runway_and_keeps_its_whole_name() -> None:
    vor = next(
        n for n in parse_earth_nav(_lines(CUSTOM_DATA / "earth_nav.dat")) if n.ident == "ZUL"
    )
    assert vor.airport_icao is None
    assert vor.runway_ident is None
    assert vor.name == "Zulu VOR/DME"
    assert vor.magnetic_variation_deg == pytest.approx(-2.0)


def test_the_localizer_and_glideslope_rows_are_decoded() -> None:
    parsed = list(parse_earth_nav(_lines(CUSTOM_DATA / "earth_nav.dat")))
    localizer = next(n for n in parsed if n.kind == "localizer")
    glideslope = next(n for n in parsed if n.kind == "glideslope")
    assert localizer.frequency_khz == 109_500
    assert localizer.true_deg == pytest.approx(90.0)
    assert localizer.mag_deg == pytest.approx(91.0)
    assert glideslope.glideslope_deg == pytest.approx(3.0)
    assert glideslope.true_deg == pytest.approx(90.0)


def test_markers_are_recognised_and_deliberately_not_indexed() -> None:
    """Nothing in the product tunes, draws or positions against a marker beacon."""
    parsed = list(parse_earth_nav(_lines(CUSTOM_DATA / "earth_nav.dat")))
    assert all(n.ident != "ZZ" for n in parsed)


def test_a_navaid_row_with_an_undecodable_bearing_is_skipped_and_counted() -> None:
    skipped: list[str] = []
    parsed = list(
        parse_earth_nav(
            _lines(CUSTOM_DATA / "earth_nav.dat"), on_skip=lambda r, _l: skipped.append(r)
        )
    )
    assert all(n.ident != "IZZY" for n in parsed)
    assert len(skipped) == 1
    assert "bearing" in skipped[0]


def test_the_default_data_copy_is_a_separate_file_with_separate_contents() -> None:
    """Per-file precedence only means anything if the two copies really differ."""
    default = {n.ident for n in parse_earth_nav(_lines(DEFAULT_DATA / "earth_nav.dat"))}
    custom = {n.ident for n in parse_earth_nav(_lines(CUSTOM_DATA / "earth_nav.dat"))}
    assert default.isdisjoint(custom)


# --------------------------------------------------------------------------
# earth_hold.dat
# --------------------------------------------------------------------------


def test_a_hold_publishes_either_a_time_leg_or_a_distance_leg() -> None:
    holds = {h.fix_ident: h for h in parse_earth_hold(_lines(DEFAULT_DATA / "earth_hold.dat"))}
    assert holds["ZUL"].leg_time_min == pytest.approx(1.0)
    assert holds["ZUL"].leg_length_nm is None
    assert holds["ZOXOL"].leg_length_nm == pytest.approx(7.0)
    assert holds["ZOXOL"].leg_time_min is None


def test_a_hold_with_neither_measure_is_skipped_and_counted() -> None:
    """A record carrying neither is not a degraded hold — it is not a hold."""
    skipped: list[str] = []
    holds = list(
        parse_earth_hold(
            _lines(DEFAULT_DATA / "earth_hold.dat"), on_skip=lambda r, _l: skipped.append(r)
        )
    )
    assert {h.fix_ident for h in holds} == {"ZUL", "ZOXOL"}
    assert len(skipped) == 1
    assert "neither" in skipped[0]


def test_zero_is_how_the_format_spells_not_published() -> None:
    holds = {h.fix_ident: h for h in parse_earth_hold(_lines(DEFAULT_DATA / "earth_hold.dat"))}
    assert holds["ZUL"].min_altitude_ft == pytest.approx(6000.0)
    assert holds["ZUL"].max_altitude_ft is None
    assert holds["ZUL"].speed_kt is None
    assert holds["ZOXOL"].speed_kt == pytest.approx(230.0)


def test_the_hold_carries_its_scope_its_fix_type_and_its_turn() -> None:
    holds = {h.fix_ident: h for h in parse_earth_hold(_lines(DEFAULT_DATA / "earth_hold.dat"))}
    assert holds["ZUL"].airport_icao == "ZZZZ"
    assert holds["ZUL"].fix_type == 3
    assert holds["ZUL"].turn_direction == "R"
    assert holds["ZUL"].inbound_course_mag_deg == pytest.approx(242.0)
    assert holds["ZOXOL"].airport_icao is None
    assert holds["ZOXOL"].fix_type == 11


@pytest.mark.parametrize(
    "row",
    [
        "ZBAD ENRT LE 11 90.0 1.0 0.0 X 0 0 0",
        "ZBAD ENRT LE 11 nope 1.0 0.0 R 0 0 0",
        "ZBAD ENRT LE 11 400.0 1.0 0.0 R 0 0 0",
        "ZBAD ENRT LE",
    ],
)
def test_a_malformed_hold_row_is_skipped_and_counted(row: str) -> None:
    skipped: list[str] = []
    holds = list(parse_earth_hold([row], on_skip=lambda r, _l: skipped.append(r)))
    assert holds == []
    assert len(skipped) == 1
