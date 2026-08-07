"""The indexed provider end to end, over the committed fixture tree.

The contract suite already proves this provider answers the same questions as
the in-memory one. What is asserted here is everything the contract cannot see
because it is specific to reading real files: per-file precedence, the merge
that produces a runway, the units that come out of the decoders, the spatial
prefilter at the antimeridian and the poles, and the shape of ``status()``.

The last section runs against the developer's **own** X-Plane installation and
is marked ``navdata`` so it never runs in CI (hard rule 4: navdata is read from
the user's install and never redistributed, so it cannot be committed as a
fixture either). Those tests deliberately assert on the *shape* of a real index
rather than on any ident, because that is the part a real install can honestly
answer — and it is where a decoder regression against real data would show up.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.models import GeoPosition
from core.navdata.models import FixRef, NavaidKind
from core.navdata.sources import cifp_file, discover_xplane_root
from core.navdata.xplane_native.provider import XPNativeNavdataProvider

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "navdata" / "xp_root"

VHF_KINDS: tuple[NavaidKind, ...] = ("vor", "vor_dme", "vortac", "dme", "tacan")
NDB_ONLY: tuple[NavaidKind, ...] = ("ndb",)
LOCALIZER_ONLY: tuple[NavaidKind, ...] = ("localizer",)

ZZZZ = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=2000.0)


@pytest.fixture
def provider(tmp_path: Path) -> Iterator[XPNativeNavdataProvider]:
    built = XPNativeNavdataProvider(FIXTURE_ROOT, cache_dir=tmp_path / "cache")
    built.ensure_index()
    yield built
    built.close()


@pytest.fixture
def wide_provider(tmp_path: Path) -> Iterator[XPNativeNavdataProvider]:
    """The fixture tree plus three fixes that only exist to exercise the box maths.

    A copy, because the committed tree is read-only source. The extra fixes sit
    either side of the antimeridian and one sits near the pole — the two places
    a latitude/longitude rectangle stops behaving like a rectangle.
    """
    root = tmp_path / "xp_root"
    shutil.copytree(FIXTURE_ROOT, root)
    fix_file = root / "Custom Data" / "earth_fix.dat"
    fix_file.write_text(
        fix_file.read_text(encoding="utf-8")
        + "   0.00000000  179.90000000 ZWEST ENRT ZZ 4530011\n"
        + "   0.00000000 -179.90000000 ZEAST ENRT ZZ 4530011\n"
        + "  89.50000000   90.00000000 ZPOLE ENRT ZZ 4530011\n",
        encoding="utf-8",
    )
    built = XPNativeNavdataProvider(root, cache_dir=tmp_path / "cache")
    built.ensure_index()
    yield built
    built.close()


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


def test_status_reports_the_cycle_the_root_and_the_counts(
    provider: XPNativeNavdataProvider,
) -> None:
    status = provider.status()
    assert status.state == "ready"
    assert status.reason is None
    assert status.provider == "xplane_native"
    assert status.source_root == str(FIXTURE_ROOT)
    assert status.airac_cycle == "2501"
    assert status.cycle_valid_from is not None
    assert status.cycle_valid_to is not None
    assert status.built_at is not None
    assert (status.airport_count, status.runway_count) == (2, 4)


def test_a_heliport_is_not_counted_as_an_airport(provider: XPNativeNavdataProvider) -> None:
    assert provider.get_airport("ZZZH") is None


# --------------------------------------------------------------------------
# Per-file precedence
# --------------------------------------------------------------------------


def test_the_default_data_copies_are_shadowed_by_custom_data(
    provider: XPNativeNavdataProvider,
) -> None:
    """A directory-level rule would be simpler and would silently lose a thousand airports."""
    assert provider.get_fixes("ZDFLT") == []
    assert provider.get_navaids("ZDEF") == []
    assert provider.get_fixes("ZOXOL")
    assert provider.get_navaids("ZUL")


def test_a_zero_byte_custom_file_falls_through_so_the_holds_still_arrive(
    provider: XPNativeNavdataProvider,
) -> None:
    """``Custom Data/earth_hold.dat`` is empty; the holds come from the default data."""
    assert {h.fix.ident for h in provider.get_holds()} == {"ZUL", "ZOXOL"}


# --------------------------------------------------------------------------
# Airports
# --------------------------------------------------------------------------


def test_the_airport_carries_everything_the_1302_rows_publish(
    provider: XPNativeNavdataProvider,
) -> None:
    airport = provider.get_airport("ZZZZ")
    assert airport is not None
    assert (airport.iata, airport.city, airport.country) == ("ZZZ", "Nowhere", "Neverland")
    assert airport.region_code == "LE"
    assert airport.transition_altitude_ft == 6000
    assert airport.transition_level_ft == 7000
    assert airport.has_tower is True
    assert airport.runway_count == 2
    assert airport.position == ZZZZ


def test_has_procedures_mirrors_the_existence_of_a_cifp_file(
    provider: XPNativeNavdataProvider,
) -> None:
    """Set from a directory listing, not a parse, so the UI can grey the tabs out early."""
    airport = provider.get_airport("ZZZZ")
    assert airport is not None
    assert airport.has_procedures == (cifp_file(FIXTURE_ROOT, "ZZZZ") is not None)


def test_search_matches_a_code_a_prefix_and_a_name_fragment(
    provider: XPNativeNavdataProvider,
) -> None:
    assert [a.icao for a in provider.search_airports("ZZZY")] == ["ZZZY"]
    assert {a.icao for a in provider.search_airports("ZZZ")} == {"ZZZZ", "ZZZY"}
    assert [a.icao for a in provider.search_airports("secondary")] == ["ZZZY"]


def test_search_is_accent_insensitive_and_case_insensitive(
    provider: XPNativeNavdataProvider,
) -> None:
    assert [a.icao for a in provider.search_airports("  FiCtIoNaL ")] == ["ZZZZ"]


def test_the_longest_runway_breaks_the_tie_within_a_rank(
    provider: XPNativeNavdataProvider,
) -> None:
    """An instructor typing "zulu" wants the 3000 m runway above the 1200 m one."""
    assert [a.icao for a in provider.search_airports("zulu")] == ["ZZZZ", "ZZZY"]


# --------------------------------------------------------------------------
# Runways — the merge
# --------------------------------------------------------------------------


def test_an_undisplaced_threshold_survives_the_round_trip_exactly(
    provider: XPNativeNavdataProvider,
) -> None:
    runway = provider.get_runway("ZZZZ", "09")
    assert runway is not None
    assert runway.threshold == ZZZZ
    assert runway.pavement_end == ZZZZ
    assert runway.displaced_threshold_m == 0.0


def test_a_displaced_threshold_arrives_walked_forward(provider: XPNativeNavdataProvider) -> None:
    runway = provider.get_runway("ZZZY", "18")
    assert runway is not None
    assert runway.pavement_end is not None
    assert runway.threshold != runway.pavement_end

    walked_nm, _ = distance_and_bearing(runway.pavement_end, runway.threshold)
    assert walked_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(300.0, abs=0.01)
    assert runway.displaced_threshold_m == pytest.approx(300.0)


def test_landing_distance_is_the_pavement_minus_the_displacement(
    provider: XPNativeNavdataProvider,
) -> None:
    runway = provider.get_runway("ZZZY", "18")
    assert runway is not None
    assert runway.landing_distance_m is not None
    assert runway.landing_distance_m == pytest.approx(runway.length_m - 300.0)


def test_the_threshold_altitude_is_the_threshold_elevation(
    provider: XPNativeNavdataProvider,
) -> None:
    runway = provider.get_runway("ZZZZ", "09")
    assert runway is not None
    assert runway.threshold.altitude_ft == runway.elevation_ft == 2000.0


def test_the_runway_carries_its_pavement_detail(provider: XPNativeNavdataProvider) -> None:
    runway = provider.get_runway("ZZZZ", "09")
    assert runway is not None
    assert runway.width_m == pytest.approx(45.0)
    assert runway.surface == "asphalt"
    assert runway.opposite_ident == "27"


def test_the_ils_arrives_on_the_runway_with_every_unit_already_right(
    provider: XPNativeNavdataProvider,
) -> None:
    """One lookup, so no caller can place an aircraft on an approach it forgot to tune."""
    runway = provider.get_runway("ZZZZ", "09")
    assert runway is not None
    ils = runway.ils
    assert ils is not None
    assert ils.localizer_ident == "IZZZ"
    assert ils.frequency_khz == 109_500
    assert ils.localizer_true_deg == pytest.approx(90.0)
    assert ils.localizer_mag_deg == pytest.approx(91.0)
    assert ils.glideslope_deg == pytest.approx(3.0)
    assert ils.glideslope_position is not None
    assert ils.has_dme is True
    # The category comes from the CIFP only, and no CIFP source is wired in here.
    assert ils.category is None


def test_a_runway_without_a_localizer_reports_no_ils(provider: XPNativeNavdataProvider) -> None:
    assert provider.get_ils("ZZZZ", "27") is None
    assert provider.get_ils("ZZZY", "36") is None


def test_a_localizer_whose_row_was_malformed_never_becomes_an_ils(
    provider: XPNativeNavdataProvider,
) -> None:
    """One bad record degrades one runway. It does not fail the build or raise later."""
    assert provider.get_navaids("IZZY") == []
    assert provider.get_ils("ZZZY", "36") is None


# --------------------------------------------------------------------------
# Parking
# --------------------------------------------------------------------------


def test_parking_metadata_becomes_tuples_not_source_strings(
    provider: XPNativeNavdataProvider,
) -> None:
    stand = next(s for s in provider.get_parking("ZZZZ") if s.name == "R32")
    assert stand.kind == "gate"
    assert stand.operation == "airline"
    assert stand.aircraft_types == ("jets", "heavy")
    assert stand.airline_codes == ("ibe", "baw")
    assert stand.heading_true_deg == pytest.approx(180.0)


def test_every_parking_kind_round_trips_through_the_index(
    provider: XPNativeNavdataProvider,
) -> None:
    kinds = {s.kind for icao in ("ZZZZ", "ZZZY") for s in provider.get_parking(icao)}
    assert kinds == {"gate", "tie_down", "hangar", "misc"}


# --------------------------------------------------------------------------
# Navaids and fixes
# --------------------------------------------------------------------------


def test_the_navaid_families_survive_indexing(provider: XPNativeNavdataProvider) -> None:
    assert provider.get_navaids("ZUL")[0].kind == "vor_dme"
    assert provider.get_navaids("ZTC")[0].kind == "tacan"
    assert provider.get_navaids("ZB")[0].kind == "ndb"
    assert {n.kind for n in provider.get_navaids("IZZZ")} == {"localizer", "glideslope", "dme"}


def test_frequencies_come_out_in_the_unit_aircraft_setup_expects(
    provider: XPNativeNavdataProvider,
) -> None:
    assert provider.get_navaids("ZUL")[0].frequency_khz == 113_700
    assert provider.get_navaids("ZB")[0].frequency_khz == 380


def test_the_terminal_scope_of_a_fix_is_preserved(provider: XPNativeNavdataProvider) -> None:
    both = provider.get_fixes("ZOXOL")
    assert len(both) == 2
    assert {f.terminal_airport_icao for f in both} == {None, "ZZZZ"}


def test_resolve_fix_walks_every_section_of_the_arinc_table(
    provider: XPNativeNavdataProvider,
) -> None:
    vor = provider.resolve_fix(FixRef(ident="ZUL", region_code="LE", section="D", subsection=""))
    assert vor is not None
    assert vor.kind == "vor"

    ndb = provider.resolve_fix(FixRef(ident="ZB", region_code="LE", section="D", subsection="B"))
    assert ndb is not None
    assert ndb.kind == "ndb"

    airport = provider.resolve_fix(
        FixRef(ident="ZZZZ", region_code="LE", section="P", subsection="A")
    )
    assert airport is not None
    assert airport.kind == "airport"

    localizer = provider.resolve_fix(
        FixRef(ident="IZZZ", region_code="LE", section="P", subsection="I", airport_icao="ZZZZ")
    )
    assert localizer is not None
    assert localizer.kind == "localizer"


def test_resolve_fix_keeps_the_terminal_and_enroute_records_apart(
    provider: XPNativeNavdataProvider,
) -> None:
    terminal = provider.resolve_fix(
        FixRef(ident="ZOXOL", region_code="LE", section="P", subsection="C", airport_icao="ZZZZ")
    )
    enroute = provider.resolve_fix(
        FixRef(ident="ZOXOL", region_code="LE", section="E", subsection="A")
    )
    assert terminal is not None
    assert enroute is not None
    assert terminal.position.latitude == pytest.approx(40.2)
    assert enroute.position.latitude == pytest.approx(40.5)


def test_an_unknown_section_resolves_to_nothing_rather_than_guessing(
    provider: XPNativeNavdataProvider,
) -> None:
    assert (
        provider.resolve_fix(FixRef(ident="ZUL", region_code="LE", section="X", subsection=""))
        is None
    )


# --------------------------------------------------------------------------
# Holds
# --------------------------------------------------------------------------


def test_a_hold_is_joined_to_a_coordinate_through_its_fix_type(
    provider: XPNativeNavdataProvider,
) -> None:
    """``earth_hold.dat`` names its fix but never positions it."""
    hold = provider.get_holds(fix_ident="ZUL")[0]
    assert hold.fix.kind == "vor"
    assert hold.fix.position.latitude == pytest.approx(40.05)
    assert hold.leg_time_min == pytest.approx(1.0)
    assert hold.airport_icao == "ZZZZ"


def test_an_enroute_hold_resolves_against_the_enroute_record_of_a_shared_ident(
    provider: XPNativeNavdataProvider,
) -> None:
    hold = provider.get_holds(fix_ident="ZOXOL")[0]
    assert hold.airport_icao is None
    assert hold.fix.position.latitude == pytest.approx(40.5)
    assert hold.leg_length_nm == pytest.approx(7.0)


# --------------------------------------------------------------------------
# Spatial queries
# --------------------------------------------------------------------------


def test_navaids_near_is_bounded_by_the_radius_and_sorted(
    provider: XPNativeNavdataProvider,
) -> None:
    near = provider.navaids_near(ZZZZ, radius_nm=5.0)
    assert {n.ident for n in near} == {"ZUL", "IZZZ"}
    distances = [distance_and_bearing(ZZZZ, n.position)[0] for n in near]
    assert distances == sorted(distances)


def test_a_spatial_query_can_be_filtered_by_kind(provider: XPNativeNavdataProvider) -> None:
    assert [n.ident for n in provider.navaids_near(ZZZZ, 100.0, kinds=NDB_ONLY)] == ["ZB"]
    assert [n.ident for n in provider.navaids_near(ZZZZ, 100.0, kinds=LOCALIZER_ONLY)] == ["IZZZ"]


def test_a_spatial_query_respects_its_limit(provider: XPNativeNavdataProvider) -> None:
    assert len(provider.navaids_near(ZZZZ, 100.0, limit=2)) == 2


def test_a_zero_radius_returns_nothing_rather_than_everything(
    provider: XPNativeNavdataProvider,
) -> None:
    assert provider.navaids_near(ZZZZ, 0.0) == []
    assert provider.fixes_near(ZZZZ, 0.0) == []


def test_the_box_is_a_prefilter_and_the_geodesic_is_the_answer(
    provider: XPNativeNavdataProvider,
) -> None:
    """A rectangle around a circle keeps the corners; the refine is what drops them.

    ZB lies 7.56 NM from the threshold, so a 7 NM search must exclude it even
    though a 7 NM latitude/longitude box comfortably contains it.
    """
    assert distance_and_bearing(ZZZZ, provider.get_navaids("ZB")[0].position)[0] == pytest.approx(
        7.561, abs=0.01
    )
    assert "ZB" not in {n.ident for n in provider.navaids_near(ZZZZ, 7.0)}
    assert "ZB" in {n.ident for n in provider.navaids_near(ZZZZ, 8.0)}


def test_a_search_across_the_antimeridian_finds_both_sides(
    wide_provider: XPNativeNavdataProvider,
) -> None:
    """``longitude BETWEEN 179.5 AND -179.5`` matches nothing, so the box is split in two."""
    centre = GeoPosition(latitude=0.0, longitude=180.0, altitude_ft=0.0)
    found = {f.ident for f in wide_provider.fixes_near(centre, radius_nm=30.0)}
    assert found == {"ZWEST", "ZEAST"}


def test_a_search_near_the_pole_drops_the_longitude_filter(
    wide_provider: XPNativeNavdataProvider,
) -> None:
    """At 89.9 N a 30 NM circle spans every meridian, so a longitude band means nothing."""
    centre = GeoPosition(latitude=89.9, longitude=0.0, altitude_ft=0.0)
    assert {f.ident for f in wide_provider.fixes_near(centre, radius_nm=31.0)} == {"ZPOLE"}
    assert wide_provider.fixes_near(centre, radius_nm=30.0) == []


# --------------------------------------------------------------------------
# Procedures — the injected seam
# --------------------------------------------------------------------------


def test_the_default_cifp_source_reports_no_procedures_rather_than_failing(
    provider: XPNativeNavdataProvider,
) -> None:
    """Correct for an airport with no CIFP file, degraded otherwise — never a crash.

    The indexed provider owns no procedure parsing: it delegates to an injected
    ``CifpSource``, and ``NullCifpSource`` is the default until the parser is
    wired in.
    """
    assert provider.get_procedures("ZZZZ") == []
    assert provider.get_procedure("ZZZZ", "sid", "ANYTHING") is None


# --------------------------------------------------------------------------
# The developer's own installation. Never runs in CI.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_install(tmp_path_factory: pytest.TempPathFactory) -> Iterator[XPNativeNavdataProvider]:
    """One index build over the user's real navdata, shared by the tests below.

    Building it is the slow part (60-120 s on a full install), so it happens
    once. The cache goes to a temporary directory rather than the user's real
    one, so running the suite never disturbs the application's own cache.
    """
    root = discover_xplane_root()
    if root is None:
        pytest.skip("No X-Plane 12 installation found. Set OIS_XPLANE_PATH to run these.")

    built = XPNativeNavdataProvider(root, cache_dir=tmp_path_factory.mktemp("navdata-real"))
    status = built.ensure_index()
    if status.state != "ready":
        pytest.skip(f"The index could not be built from {root}: {status.reason}")
    yield built
    built.close()


@pytest.mark.navdata
def test_a_real_install_indexes_a_plausible_world(real_install: XPNativeNavdataProvider) -> None:
    status = real_install.status()
    assert status.state == "ready"
    assert status.airport_count is not None
    assert status.airport_count > 10_000
    assert status.navaid_count is not None
    assert status.navaid_count > 5_000
    assert status.fix_count is not None
    assert status.fix_count > 50_000


@pytest.mark.navdata
def test_a_real_install_reports_its_airac_cycle(real_install: XPNativeNavdataProvider) -> None:
    cycle = real_install.status().airac_cycle
    assert cycle is not None
    assert cycle.isdigit()
    assert len(cycle) == 4


@pytest.mark.navdata
def test_real_runway_geometry_is_self_consistent(real_install: XPNativeNavdataProvider) -> None:
    """The decoders and the threshold walk, checked against thousands of real rows.

    A displaced threshold must lie *on* the pavement, on the runway's own
    bearing, and no further down it than the runway is long. Those three
    together are what a mis-signed displacement or a reciprocal bearing breaks.
    """
    checked = 0
    for icao in _sample_real_airports(real_install):
        for runway in real_install.get_runways(icao):
            assert 0.0 <= runway.true_bearing_deg < 360.0
            assert runway.length_m > 0.0
            assert 0.0 <= runway.displaced_threshold_m < runway.length_m
            if runway.pavement_end is not None and runway.displaced_threshold_m > 0.0:
                walked_nm, bearing = distance_and_bearing(runway.pavement_end, runway.threshold)
                assert walked_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(
                    runway.displaced_threshold_m, abs=0.5
                )
                assert bearing == pytest.approx(runway.true_bearing_deg, abs=0.5)
            checked += 1
    assert checked > 0


@pytest.mark.navdata
def test_every_real_ils_frequency_is_in_the_localizer_band(
    real_install: XPNativeNavdataProvider,
) -> None:
    """The factor-of-ten trap, checked against real records rather than a fixture."""
    found = 0
    for icao in _sample_real_airports(real_install):
        for runway in real_install.get_runways(icao):
            if runway.ils is None:
                continue
            assert 108_000 <= runway.ils.frequency_khz <= 111_950
            assert 0.0 <= runway.ils.localizer_true_deg < 360.0
            assert 0.0 <= runway.ils.localizer_mag_deg < 360.0
            if runway.ils.glideslope_deg is not None:
                assert 1.0 <= runway.ils.glideslope_deg <= 8.0
            found += 1
    assert found > 0, "No ILS was found at any sampled airport — the join or the decoder broke."


@pytest.mark.navdata
def test_a_real_install_is_adopted_on_the_second_call_without_rebuilding(
    real_install: XPNativeNavdataProvider,
) -> None:
    """The 28-day promise: every start after the first is a handful of ``stat()`` calls."""
    published = real_install.cache_path
    real_install.ensure_index()
    assert real_install.cache_path == published


def _sample_real_airports(provider: XPNativeNavdataProvider) -> list[str]:
    """A spread of real airports to assert on, without naming anyone's data as expected.

    Anything not present in the install is simply not sampled, so this is a
    sample of what is there rather than an assertion that it is there.
    """
    candidates = ("LEMD", "KSEA", "KJFK", "EGLL", "EGLC", "LSZA", "PADQ", "YSSY", "RJTT")
    return [icao for icao in candidates if provider.get_airport(icao) is not None]
