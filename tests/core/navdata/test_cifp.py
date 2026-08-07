"""The CIFP parser, against hand-written fixtures and hand-computed values.

Two kinds of test live here, and they check different things:

* **Golden values** for the decoders that are easy to get subtly wrong — packed
  DDMMSSss coordinates, tenths-of-a-degree courses, altitude bands. Every
  expected number is computed by hand in the test, so a reviewer can check it
  with a calculator rather than trusting the code under test.
* **Structure**, against ``tests/fixtures/navdata/xp_root/`` — a hand-written
  data tree in which every identifier and every coordinate is invented. Hard
  rule 4: navdata is read from the user's own install and never redistributed,
  so **no byte of any real CIFP file appears in this repository**.

The fix resolver is a dict of hand-built waypoints. That is the point of
injecting it: the parser is exercised end to end with no index, no SQLite and no
X-Plane anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.models import GeoPosition
from core.navdata.cifp_source import CifpAirport, CifpSource
from core.navdata.models import (
    MANOEUVRE_TERMINATORS,
    POSITIONABLE_TERMINATORS,
    TRAJECTORY_TERMINATORS,
    AltitudeConstraint,
    FixRef,
    ProcedureLeg,
    SpeedConstraint,
    Waypoint,
)
from core.navdata.xplane_native.cifp import (
    XPNativeCifpSource,
    decode_latitude,
    decode_longitude,
    parse_cifp,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "navdata" / "xp_root"
ZZZZ_DAT = FIXTURE_ROOT / "Custom Data" / "CIFP" / "ZZZZ.dat"
ZZZY_DAT = FIXTURE_ROOT / "Resources" / "default data" / "CIFP" / "ZZZY.dat"

#: Every field of a SID/STAR/APPCH record, by name, in source order. The parser
#: reads them positionally; naming them here is what keeps the test fixtures
#: readable and what makes an off-by-one in either place visible.
FIELD_NAMES = (
    "sequence",
    "route_type",
    "procedure",
    "transition",
    "fix_ident",
    "fix_region",
    "fix_section",
    "fix_subsection",
    "description",
    "turn",
    "rnp",
    "terminator",
    "tdv",
    "navaid_ident",
    "navaid_region",
    "navaid_section",
    "navaid_subsection",
    "arc_radius",
    "theta",
    "rho",
    "course",
    "distance",
    "alt_descriptor",
    "altitude_1",
    "altitude_2",
    "transition_altitude",
    "speed_descriptor",
    "speed_limit",
    "vertical_angle",
)
RECORD_FIELD_COUNT = 38


def record(kind: str = "SID", **values: str) -> str:
    """Build one syntactically correct 38-field procedure record."""
    unknown = set(values) - set(FIELD_NAMES)
    assert not unknown, f"not a CIFP field: {sorted(unknown)}"
    fields = [values.get(name, "") for name in FIELD_NAMES]
    fields += [""] * (RECORD_FIELD_COUNT - len(fields))
    return f"{kind}:" + ",".join(fields) + ";"


# ---------------------------------------------------------------------------
# The hand-built world the fixture's legs point at
# ---------------------------------------------------------------------------

#: Keyed by the ARINC key a leg actually names: ident plus section/subsection.
#: ``ZZMIS`` is deliberately absent — it is what exercises the "resolved fix"
#: half of ``is_positionable``.
WAYPOINTS: dict[tuple[str, str, str], Waypoint] = {
    ("ZZALF", "P", "C"): Waypoint(
        ident="ZZALF",
        kind="fix",
        position=GeoPosition(latitude=40.10, longitude=-3.10),
        region_code="ZZ",
        airport_icao="ZZZZ",
    ),
    ("ZZARC", "P", "C"): Waypoint(
        ident="ZZARC",
        kind="fix",
        position=GeoPosition(latitude=40.05, longitude=-3.05),
        region_code="ZZ",
        airport_icao="ZZZZ",
    ),
    ("ZZFAF", "P", "C"): Waypoint(
        ident="ZZFAF",
        kind="fix",
        position=GeoPosition(latitude=40.20, longitude=-3.20),
        region_code="ZZ",
        airport_icao="ZZZZ",
    ),
    ("ZZBRA", "E", "A"): Waypoint(
        ident="ZZBRA",
        kind="fix",
        position=GeoPosition(latitude=40.30, longitude=-3.30),
        region_code="ZZ",
    ),
    ("ZZCHA", "E", "A"): Waypoint(
        ident="ZZCHA",
        kind="fix",
        position=GeoPosition(latitude=40.40, longitude=-3.40),
        region_code="ZZ",
    ),
    ("ZZHLD", "E", "A"): Waypoint(
        ident="ZZHLD",
        kind="fix",
        position=GeoPosition(latitude=40.50, longitude=-3.50),
        region_code="ZZ",
    ),
    ("IZZC", "P", "I"): Waypoint(
        ident="IZZC",
        kind="localizer",
        position=GeoPosition(latitude=40.008, longitude=-3.026),
        region_code="ZZ",
        airport_icao="ZZZZ",
    ),
    ("RW32L", "P", "G"): Waypoint(
        ident="RW32L",
        kind="runway",
        position=GeoPosition(latitude=40.0083333, longitude=-3.025, altitude_ft=2040.0),
        region_code="ZZ",
        airport_icao="ZZZZ",
    ),
}


def resolver(ref: FixRef) -> Waypoint | None:
    """A :data:`FixResolver` over eight hand-built waypoints and nothing else."""
    return WAYPOINTS.get((ref.ident, ref.section, ref.subsection))


@pytest.fixture(scope="module")
def zzzz() -> CifpAirport:
    return parse_cifp(ZZZZ_DAT.read_text(encoding="utf-8"), icao="ZZZZ", resolve_fix=resolver)


def leg_of(
    airport: CifpAirport, ident: str, sequence: int, transition: str | None = None
) -> ProcedureLeg:
    """The one leg of ``ident``/``transition`` with this sequence number."""
    procedure = next(
        p for p in airport.procedures if p.ident == ident and p.transition == transition
    )
    return next(leg for leg in procedure.legs if leg.sequence == sequence)


# ---------------------------------------------------------------------------
# The fixtures themselves
# ---------------------------------------------------------------------------


class TestFixtureIntegrity:
    """The fixtures are the specification of the format; guard their shape."""

    @pytest.mark.parametrize("path", [ZZZZ_DAT, ZZZY_DAT], ids=["ZZZZ", "ZZZY"])
    def test_every_procedure_record_carries_38_fields(self, path: Path) -> None:
        """Except the one that is deliberately truncated to prove it is survived."""
        offenders = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            prefix, separator, body = line.partition(":")
            if not separator or prefix not in {"SID", "STAR", "APPCH"}:
                continue
            count = len(body.rstrip().removesuffix(";").split(","))
            if count != RECORD_FIELD_COUNT and "ZZBAD" not in body:
                offenders.append((number, count))
        assert not offenders, f"{path.name}: records with the wrong field count: {offenders}"

    @pytest.mark.parametrize("path", [ZZZZ_DAT, ZZZY_DAT], ids=["ZZZZ", "ZZZY"])
    def test_every_runway_record_carries_10_fields_and_the_embedded_semicolon(
        self, path: Path
    ) -> None:
        """The shape the real format publishes, which is what makes this fixture worth having.

        A fixture written to a parser's assumption instead of to the format
        proves nothing, so the shape itself is asserted here rather than left
        implicit in whatever the parser happens to accept.
        """
        offenders = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            prefix, separator, body = line.partition(":")
            if not separator or prefix != "RWY" or "GARBAGE" in body:
                continue
            fields = body.rstrip().removesuffix(";").split(",")
            if len(fields) != 10 or ";" not in fields[7]:
                offenders.append((number, len(fields)))
        assert not offenders, f"{path.name}: RWY: records with the wrong shape: {offenders}"

    def test_the_fixtures_stay_tiny(self) -> None:
        """A CIFP fixture that has grown is a fixture that started copying real data."""
        assert ZZZZ_DAT.stat().st_size < 8192
        assert ZZZY_DAT.stat().st_size < 2048


# ---------------------------------------------------------------------------
# Golden values — design §11.5
# ---------------------------------------------------------------------------


class TestPackedCoordinates:
    """DDMMSSss, where the last two digits are HUNDREDTHS of a second.

    Reading them as thousandths yields a coordinate a few metres away that looks
    entirely plausible, which is why every case below is written out longhand.
    """

    @pytest.mark.parametrize(
        ("packed", "expected"),
        [
            ("N40294171", 40 + 29 / 60 + 41.71 / 3600),  # 40.4949194
            ("S33565000", -(33 + 56 / 60 + 50.00 / 3600)),  # -33.9472222
            ("N00000001", 0.01 / 3600),  # one hundredth of a second from the equator
            ("N90000000", 90.0),
        ],
    )
    def test_latitude(self, packed: str, expected: float) -> None:
        decoded = decode_latitude(packed)
        assert decoded is not None
        assert decoded == pytest.approx(expected, abs=1e-9)

    @pytest.mark.parametrize(
        ("packed", "expected"),
        [
            ("W003332833", -(3 + 33 / 60 + 28.33 / 3600)),  # -3.5578694
            ("E151101200", 151 + 10 / 60 + 12.00 / 3600),  # 151.17
            ("W180000000", -180.0),
        ],
    )
    def test_longitude(self, packed: str, expected: float) -> None:
        decoded = decode_longitude(packed)
        assert decoded is not None
        assert decoded == pytest.approx(expected, abs=1e-9)

    def test_a_three_digit_longitude_is_not_a_latitude(self) -> None:
        """The 2-digit vs 3-digit degree split is the whole reason for two decoders."""
        assert decode_latitude("W003332833") is None
        assert decode_longitude("N40294171") is None

    @pytest.mark.parametrize("packed", ["", "   ", "N4029417", "X40294171", "N402941XX"])
    def test_unreadable_input_is_none_rather_than_an_exception(self, packed: str) -> None:
        assert decode_latitude(packed) is None
        assert decode_longitude(packed) is None

    def test_a_degrees_field_off_the_ellipsoid_is_rejected(self) -> None:
        """Better to admit the field is unreadable than to clamp it into range."""
        assert decode_longitude("E999000000") is None


# ---------------------------------------------------------------------------
# RWY: records
# ---------------------------------------------------------------------------


class TestRunwayRecords:
    def test_every_runway_is_read(self, zzzz: CifpAirport) -> None:
        assert [r.ident for r in zzzz.runways] == ["09", "27", "32L", "32R"]

    def test_the_ident_loses_its_rw_prefix(self, zzzz: CifpAirport) -> None:
        """``RW32L`` in the CIFP is ``32L`` everywhere else in the project."""
        assert zzzz.runway("32L") is not None
        assert zzzz.runway("RW32L") is not None

    def test_the_threshold_decodes_to_the_published_point(self, zzzz: CifpAirport) -> None:
        runway = zzzz.runway("09")
        assert runway is not None
        assert runway.threshold is not None
        assert runway.threshold.latitude == pytest.approx(40.0)
        assert runway.threshold.longitude == pytest.approx(-3.0)
        assert runway.elevation_ft == pytest.approx(2000.0)

    def test_hundredths_of_a_second_survive(self, zzzz: CifpAirport) -> None:
        """RW32R is N40 00 40.50 / W003 02 00.75 — both fractions non-zero."""
        runway = zzzz.runway("32R")
        assert runway is not None
        assert runway.threshold is not None
        assert runway.threshold.latitude == pytest.approx(40 + 40.50 / 3600, abs=1e-9)
        assert runway.threshold.longitude == pytest.approx(-(3 + 2 / 60 + 0.75 / 3600), abs=1e-9)

    def test_the_displaced_threshold_is_published_in_feet_and_carried_in_metres(
        self, zzzz: CifpAirport
    ) -> None:
        """RW27 publishes 1640 ft, which is 499.872 m — the unit change is the point."""
        runway = zzzz.runway("27")
        assert runway is not None
        assert runway.displaced_threshold_m == pytest.approx(1640 * 0.3048)

    def test_the_threshold_carries_its_own_elevation(self, zzzz: CifpAirport) -> None:
        runway = zzzz.runway("32L")
        assert runway is not None
        assert runway.threshold is not None
        assert runway.threshold.altitude_ft == pytest.approx(2040.0)

    def test_the_localizer_and_category_come_only_from_this_record(self, zzzz: CifpAirport) -> None:
        runway = zzzz.runway("32L")
        assert runway is not None
        assert runway.localizer_ident == "IZZC"
        assert runway.ils_category == "2"
        assert runway.threshold_crossing_height_ft == pytest.approx(48.0)

    def test_a_runway_without_an_ils_leaves_those_fields_blank(self, zzzz: CifpAirport) -> None:
        """RW27 has no localizer, no category and no crossing height."""
        runway = zzzz.runway("27")
        assert runway is not None
        assert runway.localizer_ident is None
        assert runway.ils_category is None
        assert runway.threshold_crossing_height_ft is None

    def test_an_unrecognised_ils_category_is_carried_raw_rather_than_raising(
        self, zzzz: CifpAirport
    ) -> None:
        """Real data holds letter codes for LDA, IGS and localizer-only installs.

        Mapping them to a closed ``Literal`` here is a ``ValidationError``
        waiting for the first unusual airport, and one odd record must never
        fail a parse (design §6.6).
        """
        runway = zzzz.runway("32R")
        assert runway is not None
        assert runway.ils_category == "Q"

    def test_a_runway_record_without_a_coordinate_pair_is_skipped_and_counted(self) -> None:
        airport = parse_cifp("RWY:RW99X,GARBAGE;", icao="ZZZZ")
        assert airport.runways == ()
        assert airport.skipped_record_count == 1

    def test_the_semicolon_buried_in_field_7_does_not_hide_the_latitude(self) -> None:
        """The record's own terminator, reused mid-record before the latitude.

        Miss it and ``[NS]DDMMSSss`` never matches, every ``RWY:`` record on
        every real airport is skipped as malformed, and the CIFP threshold
        silently loses the §7.2 precedence duel to ``apt.dat`` — the invisible
        offset between a placement and its procedure that §7.2 exists to
        prevent. This test is the only thing standing in the way of that.
        """
        line = "RWY:RW09,     ,      ,02000, ,IZZA,1,050;N40000000,W003000000,0000;"
        airport = parse_cifp(line, icao="ZZZZ")
        assert airport.skipped_record_count == 0

        runway = airport.runway("09")
        assert runway is not None
        assert runway.threshold is not None
        assert runway.threshold.latitude == pytest.approx(40.0)
        assert runway.threshold.longitude == pytest.approx(-3.0)
        assert runway.elevation_ft == pytest.approx(2000.0)
        assert runway.threshold_crossing_height_ft == pytest.approx(50.0)
        assert runway.localizer_ident == "IZZA"
        assert runway.ils_category == "1"

    def test_the_record_is_read_relative_to_its_coordinates(self) -> None:
        """A leading field more or fewer must not shift the whole record.

        The coordinate pair is unmistakable, so it anchors the read instead of
        the parser assuming the gradient/ellipsoid columns are always present.
        Here the ellipsoidal-height column is gone and every other field must
        still land.
        """
        without_gradient = "RWY:RW09,      ,01000, ,IZZA,1,050;N40000000,W003000000,0000;"
        airport = parse_cifp(without_gradient, icao="ZZZZ")
        runway = airport.runway("09")
        assert runway is not None
        assert runway.elevation_ft == pytest.approx(1000.0)
        assert runway.localizer_ident == "IZZA"
        assert runway.ils_category == "1"
        assert airport.skipped_record_count == 0


# ---------------------------------------------------------------------------
# Positionability — the flag the whole Position Manager turns on
# ---------------------------------------------------------------------------


class TestPositionability:
    ALWAYS_RESOLVES = Waypoint(
        ident="ZZANY", kind="fix", position=GeoPosition(latitude=40.0, longitude=-3.0)
    )

    @pytest.mark.parametrize(
        "terminator",
        sorted(POSITIONABLE_TERMINATORS | TRAJECTORY_TERMINATORS | MANOEUVRE_TERMINATORS),
    )
    def test_exactly_the_six_fix_carrying_terminators_are_offered(self, terminator: str) -> None:
        text = record(
            sequence="010",
            procedure="ZZTEST",
            fix_ident="ZZANY",
            fix_region="ZZ",
            fix_section="E",
            fix_subsection="A",
            terminator=terminator,
        )
        airport = parse_cifp(text, icao="ZZZZ", resolve_fix=lambda _ref: self.ALWAYS_RESOLVES)
        leg = airport.procedures[0].legs[0]
        assert leg.is_positionable is (terminator in POSITIONABLE_TERMINATORS)
        assert airport.skipped_record_count == 0

    def test_a_trajectory_leg_says_why_in_the_words_the_ui_shows(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 10, transition="RW32B")
        assert leg.path_terminator == "CA"
        assert leg.is_positionable is False
        assert leg.unpositionable_reason == (
            "trajectory-dependent leg (CA): no coordinate without the flown path"
        )

    def test_an_unresolved_fix_says_something_else_entirely(self, zzzz: CifpAirport) -> None:
        """ZZMIS is deliberately absent from the resolver.

        Confusing "this leg has no defensible coordinate" with "this leg's fix
        is missing from the index" would be a silent bug, so the two reasons do
        not share a sentence.
        """
        leg = leg_of(zzzz, "I32L", 10)
        assert leg.path_terminator == "IF"
        assert leg.is_positionable is False
        assert leg.unpositionable_reason == "fix ZZMIS/ZZ not found in the index"

    def test_the_raw_key_survives_a_failed_resolution(self, zzzz: CifpAirport) -> None:
        """``fix_ref`` is what makes an unresolved fix diagnosable rather than absent."""
        leg = leg_of(zzzz, "I32L", 10)
        assert leg.fix is None
        assert leg.fix_ref == FixRef(
            ident="ZZMIS", region_code="ZZ", section="P", subsection="C", airport_icao="ZZZZ"
        )

    def test_unpositionable_legs_are_still_returned(self, zzzz: CifpAirport) -> None:
        """An instructor reading a SID needs to see the climb leg."""
        procedure = next(p for p in zzzz.procedures if p.ident == "ZZZ1A")
        assert [leg.sequence for leg in procedure.legs] == [10, 20, 30, 40]

    def test_a_resolved_fix_rides_on_the_leg(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 20, transition="RW32B")
        assert leg.is_positionable is True
        assert leg.unpositionable_reason is None
        assert leg.fix is not None
        assert leg.fix.position.latitude == pytest.approx(40.10)

    def test_with_no_resolver_nothing_is_positionable_but_everything_is_returned(self) -> None:
        """What an instructor should see while the index is still building."""
        airport = parse_cifp(ZZZZ_DAT.read_text(encoding="utf-8"), icao="ZZZZ")
        legs = [leg for procedure in airport.procedures for leg in procedure.legs]
        assert legs
        assert not any(leg.is_positionable for leg in legs)
        assert all(leg.unpositionable_reason for leg in legs)

    def test_a_positionable_terminator_naming_no_fix_says_so(self) -> None:
        text = record(sequence="010", procedure="ZZTEST", terminator="TF")
        airport = parse_cifp(text, icao="ZZZZ", resolve_fix=resolver)
        leg = airport.procedures[0].legs[0]
        assert leg.fix_ref is None
        assert leg.unpositionable_reason == "leg carries a TF terminator but names no fix"


# ---------------------------------------------------------------------------
# Constraints — design §5.9, every row of the table
# ---------------------------------------------------------------------------


class TestAltitudeConstraints:
    @staticmethod
    def _constraint(descriptor: str, first: str, second: str = "") -> AltitudeConstraint | None:
        text = record(
            sequence="010",
            procedure="ZZTEST",
            terminator="TF",
            alt_descriptor=descriptor,
            altitude_1=first,
            altitude_2=second,
        )
        return parse_cifp(text, icao="ZZZZ").procedures[0].legs[0].altitude

    def test_at_or_above(self) -> None:
        constraint = self._constraint("+", "02400")
        assert constraint is not None
        assert (constraint.min_ft, constraint.max_ft) == (2400.0, None)
        assert constraint.suggested_ft == 2400.0

    def test_at_or_below(self) -> None:
        constraint = self._constraint("-", "05000")
        assert constraint is not None
        assert (constraint.min_ft, constraint.max_ft) == (None, 5000.0)
        assert constraint.suggested_ft == 5000.0

    def test_a_band_normalises_the_flight_level_and_keeps_the_flag(self) -> None:
        """``B,FL140,10000`` is a window; the flag is what lets the UI print FL140."""
        constraint = self._constraint("B", "FL140", "10000")
        assert constraint is not None
        assert (constraint.min_ft, constraint.max_ft) == (10000.0, 14000.0)
        assert constraint.max_is_flight_level is True
        assert constraint.min_is_flight_level is False

    def test_a_band_suggests_its_lower_bound(self) -> None:
        """An aircraft enters a window from above and the crew targets the bottom.

        Placing at the top of a FL140/10000 window puts it 4000 ft high on a
        descent profile it then cannot fly.
        """
        constraint = self._constraint("B", "FL140", "10000")
        assert constraint is not None
        assert constraint.suggested_ft == 10000.0

    def test_glideslope_intercept_is_an_at_constraint(self) -> None:
        constraint = self._constraint("J", "05500", "05500")
        assert constraint is not None
        assert (constraint.min_ft, constraint.max_ft) == (5500.0, 5500.0)
        assert constraint.suggested_ft == 5500.0

    def test_a_blank_descriptor_means_at_that_altitude(self) -> None:
        constraint = self._constraint("", "03000")
        assert constraint is not None
        assert (constraint.min_ft, constraint.max_ft) == (3000.0, 3000.0)

    def test_no_altitude_at_all_is_no_constraint(self) -> None:
        assert self._constraint("", "") is None
        assert self._constraint("+", "     ") is None

    def test_an_unreadable_altitude_is_dropped_rather_than_guessed(self) -> None:
        assert self._constraint("+", "ABCDE") is None


class TestSpeedConstraints:
    @staticmethod
    def _constraint(descriptor: str, limit: str) -> SpeedConstraint | None:
        text = record(
            sequence="010",
            procedure="ZZTEST",
            terminator="TF",
            speed_descriptor=descriptor,
            speed_limit=limit,
        )
        return parse_cifp(text, icao="ZZZZ").procedures[0].legs[0].speed

    def test_at_or_below(self) -> None:
        constraint = self._constraint("-", "210")
        assert constraint is not None
        assert (constraint.min_kt, constraint.max_kt) == (None, 210.0)
        assert constraint.suggested_kt == 210.0

    def test_at_or_above(self) -> None:
        constraint = self._constraint("+", "180")
        assert constraint is not None
        assert (constraint.min_kt, constraint.max_kt) == (180.0, None)
        assert constraint.suggested_kt == 180.0

    def test_a_blank_descriptor_is_a_ceiling_not_a_target(self) -> None:
        """An ARINC speed limit is "do not exceed" unless the record says otherwise."""
        constraint = self._constraint("", "250")
        assert constraint is not None
        assert constraint.max_kt == 250.0

    def test_no_limit_is_no_constraint(self) -> None:
        assert self._constraint("-", "") is None


# ---------------------------------------------------------------------------
# Leg geometry and role flags
# ---------------------------------------------------------------------------


class TestLegGeometry:
    def test_courses_are_tenths_of_a_degree(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 10, transition="RW32B")
        assert leg.outbound_course_mag_deg == pytest.approx(324.7)

    def test_distances_are_tenths_of_a_nautical_mile(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 40, transition="RW32B")
        assert leg.distance_nm == pytest.approx(13.8)

    def test_a_holding_leg_is_published_in_time_not_distance(self, zzzz: CifpAirport) -> None:
        """``T010`` is one minute, and it must not read as 1.0 NM."""
        leg = leg_of(zzzz, "ZZS2B", 30, transition="ZZBRA")
        assert leg.time_min == pytest.approx(1.0)
        assert leg.distance_nm is None

    def test_theta_and_rho_come_off_the_recommended_navaid(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 30, transition="RW32B")
        assert leg.theta_mag_deg == pytest.approx(180.2)
        assert leg.rho_nm == pytest.approx(5.5)
        assert leg.recommended_navaid is not None
        assert leg.recommended_navaid.ident == "IZZC"

    def test_an_rf_leg_carries_its_arc_radius(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 30, transition="RW32B")
        assert leg.path_terminator == "RF"
        assert leg.arc_radius_nm == pytest.approx(3.500)
        assert leg.turn_direction == "R"

    @pytest.mark.parametrize(
        ("published", "expected_nm"),
        [("002100", 2.100), ("001600", 1.600), ("003150", 3.150), ("003380", 3.380)],
    )
    def test_the_arc_radius_has_three_implied_decimals(
        self, published: str, expected_nm: float
    ) -> None:
        """Pinned against the shape real RF legs publish.

        Read as tenths, ``002100`` becomes a 210 NM arc; read as hundredths, a
        21 NM one. An RF turn is 2.1 NM, so the factor is worth a golden test of
        its own rather than an inference from the general "distances are tenths"
        rule, which does not apply to this field.
        """
        text = record(
            sequence="010", procedure="ZZTEST", terminator="RF", arc_radius=published, turn="R"
        )
        leg = parse_cifp(text, icao="ZZZZ").procedures[0].legs[0]
        assert leg.arc_radius_nm == pytest.approx(expected_nm)

    def test_the_vertical_angle_is_hundredths_and_keeps_its_sign(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "I32L", 20)
        assert leg.vertical_angle_deg == pytest.approx(-3.43)

    def test_the_transition_altitude_is_plain_feet(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 10, transition="RW32B")
        assert leg.transition_altitude_ft == 18000

    def test_a_course_off_the_circle_is_dropped_rather_than_wrapped(self) -> None:
        text = record(sequence="010", procedure="ZZTEST", terminator="TF", course="9999")
        leg = parse_cifp(text, icao="ZZZZ").procedures[0].legs[0]
        assert leg.outbound_course_mag_deg is None

    def test_blank_geometry_fields_are_none(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 10, transition="RW32B")
        assert leg.theta_mag_deg is None
        assert leg.rho_nm is None
        assert leg.arc_radius_nm is None
        assert leg.turn_direction is None


class TestDescriptionCode:
    """The 4-character code is positional, so its blanks are significant."""

    def test_a_flyover_waypoint(self, zzzz: CifpAirport) -> None:
        assert leg_of(zzzz, "ZZZ1A", 20, transition="RW32B").is_flyover is True

    def test_an_initial_approach_fix(self, zzzz: CifpAirport) -> None:
        assert leg_of(zzzz, "I32L", 10).is_initial_approach_fix is True

    def test_a_final_approach_fix(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "I32L", 20)
        assert leg.is_final_approach_fix is True
        assert leg.is_initial_approach_fix is False

    def test_a_missed_approach_point(self, zzzz: CifpAirport) -> None:
        assert leg_of(zzzz, "I32L", 30).is_missed_approach_point is True

    def test_a_missed_approach_leg_is_flagged_from_the_fourth_column(
        self, zzzz: CifpAirport
    ) -> None:
        """Its code is ``"   M"`` — stripping the field would lose the flag entirely."""
        leg = leg_of(zzzz, "I32L", 40)
        assert leg.is_missed_approach_leg is True
        assert leg.is_missed_approach_point is False

    def test_the_end_of_the_procedure(self, zzzz: CifpAirport) -> None:
        assert leg_of(zzzz, "I32L", 50).is_end_of_procedure is True
        assert leg_of(zzzz, "I32L", 40).is_end_of_procedure is False

    def test_a_blank_code_sets_nothing(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 10, transition="RW32B")
        assert not any(
            (
                leg.is_flyover,
                leg.is_initial_approach_fix,
                leg.is_final_approach_fix,
                leg.is_missed_approach_point,
                leg.is_missed_approach_leg,
                leg.is_end_of_procedure,
            )
        )


# ---------------------------------------------------------------------------
# Procedures and transitions
# ---------------------------------------------------------------------------


class TestProcedureAssembly:
    def test_every_procedure_is_grouped_by_ident_and_transition(self, zzzz: CifpAirport) -> None:
        assert [(p.kind, p.ident, p.transition) for p in zzzz.procedures] == [
            ("sid", "ZZZ1A", "RW32B"),
            ("star", "ZZS2B", "ZZBRA"),
            ("approach", "I32L", None),
            ("approach", "I32L", "ZZBRA"),
        ]

    def test_a_parallel_group_transition_expands_to_the_real_runways(
        self, zzzz: CifpAirport
    ) -> None:
        """``RW32B`` means "both 32s" and is expanded against the airport's own list."""
        sid = next(p for p in zzzz.procedures if p.kind == "sid")
        assert sid.transition == "RW32B"
        assert sid.runway_idents == ("32L", "32R")

    def test_a_named_transition_serves_no_specific_runway(self, zzzz: CifpAirport) -> None:
        star = next(p for p in zzzz.procedures if p.kind == "star")
        assert star.transition == "ZZBRA"
        assert star.runway_idents == ()

    def test_an_approach_takes_its_runway_from_its_own_ident(self, zzzz: CifpAirport) -> None:
        """Its transition field is blank, and expanding that would claim every runway."""
        approach = next(p for p in zzzz.procedures if p.kind == "approach" and p.transition is None)
        assert approach.runway_idents == ("32L",)
        assert approach.approach_type == "ils"

    def test_an_approach_reached_from_a_transition_keeps_the_same_runway(
        self, zzzz: CifpAirport
    ) -> None:
        approach = next(
            p for p in zzzz.procedures if p.kind == "approach" and p.transition == "ZZBRA"
        )
        assert approach.runway_idents == ("32L",)

    def test_a_blank_transition_on_a_sid_means_every_runway(self) -> None:
        text = "\n".join(
            [
                "RWY:RW09,     ,      ,02000, ,    , ,050;N40000000,W003000000,0000;",
                "RWY:RW27,     ,      ,02000, ,    , ,050;N40000000,W002540000,0000;",
                record(sequence="010", procedure="ZZCOM", terminator="CA"),
            ]
        )
        procedure = parse_cifp(text, icao="ZZZZ").procedures[0]
        assert procedure.transition is None
        assert procedure.runway_idents == ("09", "27")

    @pytest.mark.parametrize(
        ("ident", "route_type", "expected"),
        [
            ("I32L", "I", "ils"),
            ("L32L", "L", "loc"),
            ("R32L", "R", "rnav"),
            ("D32L", "D", "vor_dme"),
            ("N32L", "N", "ndb"),
            ("X32L", "X", "lda"),
            ("T32L", "T", "unknown"),
            ("A32L", "", "unknown"),
        ],
    )
    def test_the_approach_type_comes_from_the_route_type_field(
        self, ident: str, route_type: str, expected: str
    ) -> None:
        """An unrecognised code labels the approach conservatively; it never fails it."""
        text = record(
            kind="APPCH",
            sequence="010",
            route_type=route_type,
            procedure=ident,
            terminator="CA",
        )
        assert parse_cifp(text, icao="ZZZZ").procedures[0].approach_type == expected

    def test_a_circling_approach_serves_no_runway(self) -> None:
        text = "\n".join(
            [
                "RWY:RW09,     ,      ,02000, ,    , ,050;N40000000,W003000000,0000;",
                record(kind="APPCH", sequence="010", route_type="V", procedure="VOR-A",
                       terminator="CA"),
            ]
        )  # fmt: skip
        procedure = parse_cifp(text, icao="ZZZZ").procedures[0]
        assert procedure.runway_idents == ()
        assert procedure.approach_type == "vor"

    def test_only_sid_star_and_appch_records_become_procedures(self, zzzz: CifpAirport) -> None:
        assert {p.kind for p in zzzz.procedures} == {"sid", "star", "approach"}

    def test_the_airport_scopes_every_terminal_fix_reference(self, zzzz: CifpAirport) -> None:
        refs = [
            leg.fix_ref
            for procedure in zzzz.procedures
            for leg in procedure.legs
            if leg.fix_ref is not None
        ]
        assert refs
        assert all(ref.airport_icao == "ZZZZ" for ref in refs)

    def test_the_icao_is_normalised(self) -> None:
        assert parse_cifp("", icao=" zzzz ").icao == "ZZZZ"

    def test_the_raw_line_is_kept_for_diagnostics(self, zzzz: CifpAirport) -> None:
        leg = leg_of(zzzz, "ZZZ1A", 10, transition="RW32B")
        assert leg.raw is not None
        assert leg.raw.startswith("SID:010,")


# ---------------------------------------------------------------------------
# Malformed input — skipped and counted, never fatal (design §4.6)
# ---------------------------------------------------------------------------


class TestMalformedRecords:
    def test_the_fixture_counts_its_two_deliberate_offenders(self, zzzz: CifpAirport) -> None:
        """One truncated procedure record, one runway record with no coordinates."""
        assert zzzz.skipped_record_count == 2

    def test_a_truncated_record_does_not_cost_the_others(self, zzzz: CifpAirport) -> None:
        sid = next(p for p in zzzz.procedures if p.kind == "sid")
        assert len(sid.legs) == 4

    @pytest.mark.parametrize(
        "line",
        [
            "SID:010,5,ZZZ1A,RW32B,ZZBAD;",  # truncated
            "SID:" + ",".join([""] * 38) + ";",  # no sequence, ident or terminator
        ],
    )
    def test_each_shape_of_broken_record_is_counted_once(self, line: str) -> None:
        airport = parse_cifp(line, icao="ZZZZ")
        assert airport.procedures == ()
        assert airport.skipped_record_count == 1

    def test_an_unknown_path_terminator_is_malformed(self) -> None:
        """It cannot be typed, and inventing a leg type would be worse than skipping."""
        text = record(sequence="010", procedure="ZZTEST", terminator="QQ")
        airport = parse_cifp(text, icao="ZZZZ")
        assert airport.skipped_record_count == 1

    def test_a_record_type_this_project_does_not_read_is_not_malformed(self) -> None:
        """``PRDAT:`` is a known record, simply not ours. Counting it would cry wolf."""
        airport = parse_cifp("PRDAT:ZZZ1A,RW32B,IGNORED,0,0;", icao="ZZZZ")
        assert airport.skipped_record_count == 0

    def test_blank_lines_and_prose_are_ignored(self) -> None:
        airport = parse_cifp("\n\n   \n# a comment\nnot a record at all\n", icao="ZZZZ")
        assert airport.skipped_record_count == 0
        assert airport.procedures == ()

    def test_an_empty_file_is_an_empty_airport_not_an_exception(self) -> None:
        airport = parse_cifp("", icao="ZZZZ")
        assert airport == CifpAirport(icao="ZZZZ")

    def test_a_resolver_that_raises_is_the_callers_bug_not_swallowed(self) -> None:
        """The parser survives bad *data*; it does not paper over a broken index."""

        def explode(_ref: FixRef) -> Waypoint | None:
            raise RuntimeError("index is on fire")

        text = record(
            sequence="010",
            procedure="ZZTEST",
            terminator="TF",
            fix_ident="ZZANY",
            fix_region="ZZ",
            fix_section="E",
            fix_subsection="A",
        )
        with pytest.raises(RuntimeError):
            parse_cifp(text, icao="ZZZZ", resolve_fix=explode)


# ---------------------------------------------------------------------------
# The Protocol
# ---------------------------------------------------------------------------


def test_the_source_satisfies_the_cifp_source_protocol() -> None:
    assert isinstance(XPNativeCifpSource(FIXTURE_ROOT), CifpSource)
