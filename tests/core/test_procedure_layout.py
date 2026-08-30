"""``core.procedure_layout``, against the ``ZZZZ`` CIFP fixture and hand-built procedures.

The ``ZZZZ`` cases exercise real parsed data — the same fixture
``tests/core/navdata/test_cifp.py`` uses, reparsed here with the same eight
hand-built waypoints — so the algorithm is checked against exactly the
awkward shapes that fixture is designed to have: ``I32L``'s first leg with an
intentionally unresolved fix, its missed-approach tail, ``ZZZ1A``'s SID with
no runway leg of its own, and ``ZZS2B``'s zero-length segment. Compression
itself is checked against small hand-built procedures instead, where the
"real" and "capped" lengths can be stated as round numbers.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.models import GeoPosition, Runway
from core.navdata.models import (
    Airport,
    AltitudeConstraint,
    FixRef,
    Procedure,
    ProcedureLayout,
    ProcedureLeg,
    Waypoint,
)
from core.navdata.xplane_native.cifp import parse_cifp
from core.procedure_layout import LONG_FACTOR, NOMINAL_LEG_NM, procedure_layout

REPO_ROOT = Path(__file__).resolve().parents[2]
ZZZZ_DAT = (
    REPO_ROOT / "tests" / "fixtures" / "navdata" / "xp_root" / "Custom Data" / "CIFP" / "ZZZZ.dat"
)

_EPSILON_NM = 1e-6

#: Mirrors ``tests/core/navdata/test_cifp.py``'s ``WAYPOINTS`` — the same fixture, the same
#: eight resolved fixes. ``ZZMIS`` (I32L's first leg) is deliberately absent from both: it is
#: what exercises the unresolved-first-leg case.
_WAYPOINTS: dict[tuple[str, str, str], Waypoint] = {
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


def _resolver(ref: FixRef) -> Waypoint | None:
    return _WAYPOINTS.get((ref.ident, ref.section, ref.subsection))


#: A hand-built ``Airport`` for the fixture: no ``apt.dat`` entry exists for ``ZZZZ``, so its
#: reference point is invented, close to the fixture's own coordinates.
AIRPORT = Airport(
    icao="ZZZZ",
    name="Test Airport ZZZZ",
    position=GeoPosition(latitude=40.00, longitude=-3.00, altitude_ft=2040.0),
    elevation_ft=2040.0,
)

RUNWAY_32L = Runway(
    airport_icao="ZZZZ",
    ident="32L",
    threshold=_WAYPOINTS[("RW32L", "P", "G")].position,
    true_bearing_deg=322.0,
    length_m=3000.0,
    elevation_ft=2040.0,
)


@pytest.fixture(scope="module")
def zzzz_procedures() -> list[Procedure]:
    airport = parse_cifp(ZZZZ_DAT.read_text(encoding="utf-8"), icao="ZZZZ", resolve_fix=_resolver)
    return list(airport.procedures)


def _procedure(procedures: list[Procedure], kind: str, ident: str) -> Procedure:
    return next(p for p in procedures if p.kind == kind and p.ident == ident)


# ---------------------------------------------------------------------------
# Invariants — checked on every layout this module produces
# ---------------------------------------------------------------------------


def _assert_invariants(procedure: Procedure, layout: ProcedureLayout) -> None:
    legs = sorted(procedure.legs, key=lambda leg: leg.sequence)
    assert len(layout.nodes) == len(legs)
    assert [node.sequence for node in layout.nodes] == [leg.sequence for leg in legs]
    for segment in layout.segments:
        assert segment.drawn_length_nm <= segment.true_length_nm + _EPSILON_NM
        assert 0.0 <= segment.bearing_deg < 360.0


# ---------------------------------------------------------------------------
# I32L — the common route: published/runway altitude, the unresolved first
# leg, the missed-approach tail
# ---------------------------------------------------------------------------


class TestI32L:
    @pytest.fixture()
    def procedure(self, zzzz_procedures: list[Procedure]) -> Procedure:
        return _procedure(zzzz_procedures, "approach", "I32L")

    @pytest.fixture()
    def layout(self, procedure: Procedure) -> ProcedureLayout:
        return procedure_layout(procedure, AIRPORT)

    def test_anchors_at_the_runway_threshold(self, layout: ProcedureLayout) -> None:
        assert layout.anchor == "runway"
        runway_node = next(node for node in layout.nodes if node.is_runway)
        assert runway_node.ident == "32L"  # the CIFP parser strips the RW prefix
        assert runway_node.x_nm == pytest.approx(0.0, abs=_EPSILON_NM)
        assert runway_node.y_nm == pytest.approx(0.0, abs=_EPSILON_NM)
        assert runway_node.altitude_ft == pytest.approx(2090.0)
        # TF RW32L carries its own published altitude constraint in the fixture, which wins
        # over the runway's own elevation per the precedence "published" beats "runway".
        assert runway_node.altitude_source == "published"

    def test_the_first_leg_is_unresolved_and_unpositioned(self, layout: ProcedureLayout) -> None:
        first = layout.nodes[0]
        assert first.ident == "ZZMIS"
        assert first.positioned is False
        assert first.is_positionable is False

    def test_the_missed_approach_tail_is_flagged_and_keeps_walking(
        self, layout: ProcedureLayout
    ) -> None:
        by_sequence = {node.sequence: node for node in layout.nodes}
        climb = by_sequence[40]
        hold = by_sequence[50]
        assert climb.is_missed_approach is True
        assert climb.positioned is False
        assert hold.is_missed_approach is False  # HM legs carry is_end_of_procedure, not this
        assert hold.positioned is True
        assert hold.ident == "ZZHLD"

    def test_invariants(self, procedure: Procedure, layout: ProcedureLayout) -> None:
        _assert_invariants(procedure, layout)


# ---------------------------------------------------------------------------
# ZZZ1A / RW32B — a SID with no runway leg of its own, anchored via a
# supplied Runway
# ---------------------------------------------------------------------------


class TestZZZ1ASid:
    @pytest.fixture()
    def procedure(self, zzzz_procedures: list[Procedure]) -> Procedure:
        return _procedure(zzzz_procedures, "sid", "ZZZ1A")

    def test_no_leg_of_its_own_touches_a_runway_fix(self, procedure: Procedure) -> None:
        assert not any(leg.fix is not None and leg.fix.kind == "runway" for leg in procedure.legs)

    def test_without_a_runway_it_falls_back_to_last_fix(self, procedure: Procedure) -> None:
        layout = procedure_layout(procedure, AIRPORT)
        assert layout.anchor == "last_fix"

    def test_with_a_runway_it_anchors_at_the_threshold_outside_the_node_list(
        self, procedure: Procedure
    ) -> None:
        layout = procedure_layout(procedure, AIRPORT, runway=RUNWAY_32L)
        assert layout.anchor == "runway"
        assert not any(node.is_runway for node in layout.nodes)
        # The first leg (a fix-less CA) is walked outward from the threshold, not from (0, 0)
        # coinciding with any node of its own.
        first = layout.nodes[0]
        assert (first.x_nm, first.y_nm) != (0.0, 0.0)
        assert math.hypot(first.x_nm, first.y_nm) == pytest.approx(NOMINAL_LEG_NM, rel=0.05)

    def test_invariants(self, procedure: Procedure) -> None:
        layout = procedure_layout(procedure, AIRPORT, runway=RUNWAY_32L)
        _assert_invariants(procedure, layout)


# ---------------------------------------------------------------------------
# ZZS2B — the STAR: last_fix anchor, the zero-length ZZCHA segment
# ---------------------------------------------------------------------------


class TestZZS2BStar:
    @pytest.fixture()
    def procedure(self, zzzz_procedures: list[Procedure]) -> Procedure:
        return _procedure(zzzz_procedures, "star", "ZZS2B")

    @pytest.fixture()
    def layout(self, procedure: Procedure) -> ProcedureLayout:
        return procedure_layout(procedure, AIRPORT)

    def test_anchors_at_its_last_fix_not_the_airport(
        self, procedure: Procedure, layout: ProcedureLayout
    ) -> None:
        assert layout.anchor == "last_fix"
        last_leg = max(procedure.legs, key=lambda leg: leg.sequence)
        last_node = layout.nodes[-1]
        assert last_node.sequence == last_leg.sequence
        assert (last_node.x_nm, last_node.y_nm) == (0.0, 0.0)
        # The airport is drawn beyond it, not at the same point.
        assert (layout.airport_x_nm, layout.airport_y_nm) != (0.0, 0.0)

    def test_the_zero_length_zzcha_segment_does_not_crash_or_compress(
        self, layout: ProcedureLayout
    ) -> None:
        zero_length = [s for s in layout.segments if s.true_length_nm < _EPSILON_NM]
        assert zero_length, "ZZS2B's ZZCHA->ZZCHA segment should be present and zero-length"
        for segment in zero_length:
            assert segment.scale == "to_scale"
            assert 0.0 <= segment.bearing_deg < 360.0  # never NaN/undefined

    def test_invariants(self, procedure: Procedure, layout: ProcedureLayout) -> None:
        _assert_invariants(procedure, layout)


# ---------------------------------------------------------------------------
# Compression — hand-built procedures, round numbers
# ---------------------------------------------------------------------------


def _fixed_leg(sequence: int, ident: str, lat: float, lon: float) -> ProcedureLeg:
    return ProcedureLeg(
        sequence=sequence,
        path_terminator="TF",
        is_positionable=True,
        fix=Waypoint(ident=ident, kind="fix", position=GeoPosition(latitude=lat, longitude=lon)),
    )


class TestCompression:
    def test_a_segment_past_three_times_the_median_is_capped_and_flagged(self) -> None:
        # Four fixes on the same meridian, 1 NM apart, then one 40 NM further out: three short
        # segments (median 1 NM, cap 3 NM) and one long one that must compress.
        procedure = Procedure(
            airport_icao="ZZZZ",
            kind="star",
            ident="TEST1",
            legs=(
                _fixed_leg(10, "A", 40.00, -3.00),
                _fixed_leg(20, "B", 40.0167, -3.00),  # ~1 NM north
                _fixed_leg(30, "C", 40.0333, -3.00),  # ~1 NM further
                _fixed_leg(40, "D", 40.05, -3.00),  # ~1 NM further
                _fixed_leg(50, "E", 40.7167, -3.00),  # ~40 NM further
            ),
        )
        layout = procedure_layout(procedure, AIRPORT)
        assert layout.compressed_segment_count == 1
        long_segment = layout.segments[-1]
        assert long_segment.scale == "compressed"
        assert long_segment.true_length_nm == pytest.approx(40.0, rel=0.02)
        assert long_segment.drawn_length_nm < long_segment.true_length_nm
        assert long_segment.drawn_length_nm <= LONG_FACTOR * 1.0 + 0.1
        for segment in layout.segments[:-1]:
            assert segment.scale == "to_scale"
        _assert_invariants(procedure, layout)

    def test_fewer_than_three_segments_never_compresses(self) -> None:
        procedure = Procedure(
            airport_icao="ZZZZ",
            kind="star",
            ident="TEST2",
            legs=(
                _fixed_leg(10, "A", 40.00, -3.00),
                _fixed_leg(20, "B", 40.7167, -3.00),  # ~40 NM — would dwarf a real median
            ),
        )
        layout = procedure_layout(procedure, AIRPORT)
        assert layout.compressed_segment_count == 0
        assert layout.segments[0].scale == "to_scale"
        assert layout.segments[0].drawn_length_nm == pytest.approx(
            layout.segments[0].true_length_nm
        )


# ---------------------------------------------------------------------------
# Altitude interpolation and the flat/unknown fallback
# ---------------------------------------------------------------------------


class TestAltitude:
    def test_interpolates_linearly_between_the_nearest_known_neighbours(self) -> None:
        published = AltitudeConstraint(descriptor="+", min_ft=6000.0)
        near_field = AltitudeConstraint(descriptor="+", min_ft=2000.0)
        procedure = Procedure(
            airport_icao="ZZZZ",
            kind="star",
            ident="TEST3",
            legs=(
                ProcedureLeg(
                    sequence=10,
                    path_terminator="TF",
                    is_positionable=True,
                    fix=Waypoint(
                        ident="A", kind="fix", position=GeoPosition(latitude=40.00, longitude=-3.00)
                    ),
                    altitude=published,
                ),
                ProcedureLeg(
                    sequence=20,
                    path_terminator="TF",
                    is_positionable=True,
                    fix=Waypoint(
                        ident="B", kind="fix", position=GeoPosition(latitude=40.05, longitude=-3.00)
                    ),
                ),
                ProcedureLeg(
                    sequence=30,
                    path_terminator="TF",
                    is_positionable=True,
                    fix=Waypoint(
                        ident="C", kind="fix", position=GeoPosition(latitude=40.10, longitude=-3.00)
                    ),
                    altitude=near_field,
                ),
            ),
        )
        layout = procedure_layout(procedure, AIRPORT)
        middle = next(node for node in layout.nodes if node.sequence == 20)
        assert middle.altitude_source == "interpolated"
        assert near_field.min_ft is not None
        assert published.min_ft is not None
        assert near_field.min_ft < middle.altitude_ft < published.min_ft

    def test_with_nothing_known_anywhere_it_is_flat_at_field_elevation(self) -> None:
        procedure = Procedure(
            airport_icao="ZZZZ",
            kind="star",
            ident="TEST4",
            legs=(
                _fixed_leg(10, "A", 40.00, -3.00),
                _fixed_leg(20, "B", 40.05, -3.00),
            ),
        )
        layout = procedure_layout(procedure, AIRPORT)
        assert all(node.altitude_source == "unknown" for node in layout.nodes)
        assert all(node.altitude_ft == pytest.approx(AIRPORT.elevation_ft) for node in layout.nodes)


def test_a_procedure_with_no_legs_returns_an_empty_layout_rather_than_crashing() -> None:
    procedure = Procedure(airport_icao="ZZZZ", kind="star", ident="EMPTY", legs=())
    layout = procedure_layout(procedure, AIRPORT)
    assert layout.nodes == ()
    assert layout.segments == ()
    assert layout.anchor == "last_fix"
