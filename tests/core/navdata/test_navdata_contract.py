"""THE ``NavdataProvider`` contract suite.

Every provider must pass every test here, for the same reason every adapter must
pass ``tests/adapters/test_contract.py``: **an interface with one implementation
is a suggestion.** A second implementation that has to satisfy the same
assertions is what makes X-Plane file-format assumptions impossible to smuggle
into ``core/``.

The parametrisation grows as implementations land:

===========================  =========================================  =======
Parameter                    Data                                        In CI
===========================  =========================================  =======
``in_memory``                hand-built models, in this module           yes
``xplane_native`` (fixture)  the committed hand-written fixture tree     yes
``xplane_native`` (install)  the developer's own X-Plane                 no
===========================  =========================================  =======

The second row is the interesting one and it is why this suite differs from the
adapter one: a simulator cannot be installed on a GitHub runner, but a small
hand-written data tree can be committed. So the real parsers — the code most
likely to break — are covered on every OS in CI, without a byte of anyone's
proprietary navdata.

**The world below is invented.** ``ZZZZ`` is the ICAO code meaning "no
location", and every ident, frequency and coordinate here was chosen to make the
expected values checkable by hand: the runway threshold sits at exactly
40°00'00"N 003°00'00"W on a true bearing of 090°.
"""

from __future__ import annotations

import threading

import pytest

from core.geodesy import distance_and_bearing
from core.models import GeoPosition, Ils, Runway
from core.navdata.in_memory import InMemoryNavdataProvider
from core.navdata.models import (
    Airport,
    Fix,
    FixRef,
    Hold,
    Navaid,
    NavaidKind,
    ParkingStand,
    Procedure,
    ProcedureLeg,
    Waypoint,
)
from core.navdata.provider import NavdataProvider

#: Kind filters, named so the Literal survives into the call. An inline
#: ``("ndb",)`` is inferred as ``tuple[str]`` and does not type-check.
NDB_ONLY: tuple[NavaidKind, ...] = ("ndb",)
VOR_DME_ONLY: tuple[NavaidKind, ...] = ("vor_dme",)
GLIDESLOPE_ONLY: tuple[NavaidKind, ...] = ("glideslope",)

# --------------------------------------------------------------------------
# The invented world
# --------------------------------------------------------------------------

THRESHOLD = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=2000.0)

AIRPORT = Airport(
    icao="ZZZZ",
    iata="ZZZ",
    name="Zulu Fictional",
    city="Nowhere",
    region_code="LE",
    position=GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=2000.0),
    elevation_ft=2000.0,
    runway_count=2,
    longest_runway_m=3000.0,
    has_procedures=True,
)

#: A second airport whose name shares a prefix with the first, so the search
#: ranking has something to rank.
OTHER_AIRPORT = Airport(
    icao="ZZZY",
    name="Zulu Secondary",
    position=GeoPosition(latitude=41.0, longitude=-3.0, altitude_ft=1000.0),
    elevation_ft=1000.0,
    runway_count=1,
    longest_runway_m=1200.0,
)

ILS_09 = Ils(
    airport_icao="ZZZZ",
    runway_ident="09",
    localizer_ident="IZZZ",
    frequency_khz=109_500,
    localizer_position=GeoPosition(latitude=40.0, longitude=-2.96, altitude_ft=2000.0),
    localizer_true_deg=90.0,
    localizer_mag_deg=91.0,
    glideslope_deg=3.0,
    category="I",
)

RUNWAY_09 = Runway(
    airport_icao="ZZZZ",
    ident="09",
    threshold=THRESHOLD,
    true_bearing_deg=90.0,
    length_m=3000.0,
    elevation_ft=2000.0,
    opposite_ident="27",
    width_m=45.0,
    surface="asphalt",
    ils=ILS_09,
)

RUNWAY_27 = Runway(
    airport_icao="ZZZZ",
    ident="27",
    threshold=GeoPosition(latitude=40.0, longitude=-2.9648, altitude_ft=2000.0),
    true_bearing_deg=270.0,
    length_m=3000.0,
    elevation_ft=2000.0,
    opposite_ident="09",
)

STAND_R32 = ParkingStand(
    airport_icao="ZZZZ",
    name="R32",
    position=GeoPosition(latitude=40.002, longitude=-3.002, altitude_ft=2000.0),
    heading_true_deg=180.0,
    kind="gate",
    aircraft_types=("jets", "heavy"),
    operation="airline",
    airline_codes=("ibe",),
)

STAND_GA1 = ParkingStand(
    airport_icao="ZZZZ",
    name="GA1",
    position=GeoPosition(latitude=40.003, longitude=-3.003, altitude_ft=2000.0),
    heading_true_deg=90.0,
    kind="tie_down",
    operation="general_aviation",
)

VOR_ZUL = Navaid(
    ident="ZUL",
    kind="vor_dme",
    name="Zulu VOR",
    position=GeoPosition(latitude=40.05, longitude=-3.05, altitude_ft=2000.0),
    frequency_khz=113_700,
    range_nm=130.0,
    region_code="LE",
    tunable_radio="nav",
)

NDB_ZB = Navaid(
    ident="ZB",
    kind="ndb",
    name="Zulu Beacon",
    position=GeoPosition(latitude=40.10, longitude=-3.10, altitude_ft=2000.0),
    frequency_khz=380,
    region_code="LE",
    tunable_radio="adf",
)

GS_09 = Navaid(
    ident="IZZZ",
    kind="glideslope",
    position=GeoPosition(latitude=40.0, longitude=-2.99, altitude_ft=2000.0),
    airport_icao="ZZZZ",
    runway_ident="09",
    region_code="LE",
    tunable_radio=None,
)

LOC_09 = Navaid(
    ident="IZZZ",
    kind="localizer",
    position=ILS_09.localizer_position,
    frequency_khz=109_500,
    airport_icao="ZZZZ",
    runway_ident="09",
    region_code="LE",
    tunable_radio="nav",
)

#: An enroute fix and a terminal fix that deliberately **share an identifier**.
#: Collapsing the terminal scope would make them indistinguishable, and roughly
#: half the legs of a typical SID resolve through that scope.
ENROUTE_FIX = Fix(
    ident="ZOXOL",
    position=GeoPosition(latitude=40.5, longitude=-3.5, altitude_ft=0.0),
    region_code="LE",
)

TERMINAL_FIX = Fix(
    ident="ZOXOL",
    position=GeoPosition(latitude=40.2, longitude=-3.2, altitude_ft=0.0),
    region_code="LE",
    terminal_airport_icao="ZZZZ",
)

HOLD_ZUL = Hold(
    fix=Waypoint(ident="ZUL", kind="vor", position=VOR_ZUL.position, region_code="LE"),
    inbound_course_mag_deg=242.0,
    turn_direction="R",
    leg_time_min=1.0,
    min_altitude_ft=6000.0,
    airport_icao="ZZZZ",
)

POSITIONABLE_LEG = ProcedureLeg(
    sequence=10,
    path_terminator="IF",
    is_positionable=True,
    fix_ref=FixRef(ident="ZOXOL", region_code="LE", section="P", subsection="C",
                   airport_icao="ZZZZ"),
    fix=Waypoint(ident="ZOXOL", kind="fix", position=TERMINAL_FIX.position, region_code="LE",
                 airport_icao="ZZZZ"),
)  # fmt: skip

CLIMB_LEG = ProcedureLeg(
    sequence=20,
    path_terminator="CA",
    is_positionable=False,
    unpositionable_reason="trajectory-dependent leg (CA): no coordinate without the flown path",
)

SID_ZULU1A = Procedure(
    airport_icao="ZZZZ",
    kind="sid",
    ident="ZULU1A",
    transition=None,
    runway_idents=("09",),
    legs=(POSITIONABLE_LEG, CLIMB_LEG),
)

APPROACH_I09 = Procedure(
    airport_icao="ZZZZ",
    kind="approach",
    ident="I09",
    transition="ZOXOL",
    runway_idents=("09",),
    approach_type="ils",
    legs=(POSITIONABLE_LEG,),
)


def _build_in_memory() -> InMemoryNavdataProvider:
    return InMemoryNavdataProvider(
        airports=[AIRPORT, OTHER_AIRPORT],
        runways=[RUNWAY_09, RUNWAY_27],
        parking=[STAND_R32, STAND_GA1],
        navaids=[VOR_ZUL, NDB_ZB, LOC_09, GS_09],
        fixes=[ENROUTE_FIX, TERMINAL_FIX],
        holds=[HOLD_ZUL],
        procedures=[SID_ZULU1A, APPROACH_I09],
    )


PROVIDER_PARAMS = [
    pytest.param("in_memory", id="in_memory"),
    # The xplane_native rows arrive with the indexer (#5): one over the committed
    # fixture tree (CI), one over the developer's install (marks=navdata).
]


@pytest.fixture(params=PROVIDER_PARAMS)
def provider(request: pytest.FixtureRequest) -> NavdataProvider:
    if request.param == "in_memory":
        return _build_in_memory()
    raise ValueError(f"Unknown provider {request.param!r}")


# --------------------------------------------------------------------------
# Identity and status
# --------------------------------------------------------------------------


def test_provider_satisfies_the_protocol(provider: NavdataProvider) -> None:
    assert isinstance(provider, NavdataProvider)


def test_name_is_a_stable_identifier(provider: NavdataProvider) -> None:
    assert provider.name
    assert provider.name == provider.name


def test_status_reports_a_state_and_the_provider_name(provider: NavdataProvider) -> None:
    status = provider.status()
    assert status.provider == provider.name
    assert status.state in {"unavailable", "building", "ready", "error"}


def test_status_gives_a_reason_whenever_it_is_not_ready(provider: NavdataProvider) -> None:
    """The UI shows this string. "Unavailable" with no reason is not actionable."""
    status = provider.status()
    if status.state != "ready":
        assert status.reason, "A provider that is not ready must say why."


def test_ensure_index_is_idempotent(provider: NavdataProvider) -> None:
    first = provider.ensure_index()
    second = provider.ensure_index()
    assert first.state == second.state


def test_ensure_index_accepts_a_cancel_event(provider: NavdataProvider) -> None:
    """Cancellation is a parameter, not a convention.

    A provider with nothing to build ignores it; one with a build must abandon
    the partial work and publish nothing. Either way the call returns a status
    rather than raising.
    """
    cancel = threading.Event()
    cancel.set()
    assert provider.ensure_index(cancel=cancel).provider == provider.name


# --------------------------------------------------------------------------
# Not-found is never an exception
# --------------------------------------------------------------------------


def test_unknown_airport_returns_none(provider: NavdataProvider) -> None:
    assert provider.get_airport("XXXX") is None


def test_unknown_runway_returns_none(provider: NavdataProvider) -> None:
    assert provider.get_runway("ZZZZ", "99") is None


def test_unknown_collections_return_empty_lists(provider: NavdataProvider) -> None:
    assert provider.get_runways("XXXX") == []
    assert provider.get_parking("XXXX") == []
    assert provider.get_procedures("XXXX") == []
    assert provider.get_navaids("XXXX") == []
    assert provider.get_fixes("XXXX") == []


def test_unknown_procedure_returns_none(provider: NavdataProvider) -> None:
    assert provider.get_procedure("ZZZZ", "sid", "NOSUCH") is None


# --------------------------------------------------------------------------
# Airports
# --------------------------------------------------------------------------


def test_get_airport_is_case_insensitive(provider: NavdataProvider) -> None:
    assert provider.get_airport("zzzz") is not None
    assert provider.get_airport("  ZZZZ ") is not None


def test_search_ranks_an_exact_icao_first(provider: NavdataProvider) -> None:
    results = provider.search_airports("ZZZZ")
    assert results
    assert results[0].icao == "ZZZZ"


def test_search_matches_a_name_fragment(provider: NavdataProvider) -> None:
    assert {a.icao for a in provider.search_airports("fictional")} == {"ZZZZ"}


def test_search_respects_its_limit(provider: NavdataProvider) -> None:
    assert len(provider.search_airports("zulu", limit=1)) == 1


def test_search_of_nothing_returns_nothing(provider: NavdataProvider) -> None:
    assert provider.search_airports("   ") == []


def test_airports_near_is_bounded_by_the_radius(provider: NavdataProvider) -> None:
    """ZZZY is a degree of latitude away — 60 NM — so a 10 NM search excludes it."""
    near = provider.airports_near(AIRPORT.position, radius_nm=10.0)
    assert {a.icao for a in near} == {"ZZZZ"}

    wide = provider.airports_near(AIRPORT.position, radius_nm=100.0)
    assert {a.icao for a in wide} == {"ZZZZ", "ZZZY"}


def test_airports_near_is_sorted_by_distance(provider: NavdataProvider) -> None:
    near = provider.airports_near(AIRPORT.position, radius_nm=100.0)
    assert [a.icao for a in near] == ["ZZZZ", "ZZZY"]


# --------------------------------------------------------------------------
# Runways
# --------------------------------------------------------------------------


def test_each_runway_end_is_its_own_entry(provider: NavdataProvider) -> None:
    """18L and 36R are two runways: a placement is always relative to one end."""
    idents = [r.ident for r in provider.get_runways("ZZZZ")]
    assert idents == sorted(idents)
    assert set(idents) == {"09", "27"}


def test_runway_ident_is_accepted_in_either_spelling(provider: NavdataProvider) -> None:
    """The CIFP says RW09 and apt.dat says 09. Callers should not have to care."""
    from_apt = provider.get_runway("ZZZZ", "09")
    from_cifp = provider.get_runway("ZZZZ", "RW09")
    assert from_apt is not None
    assert from_cifp is not None
    assert from_apt.ident == from_cifp.ident == "09"


def test_runway_carries_its_ils(provider: NavdataProvider) -> None:
    """One lookup, so no caller can place an aircraft on an approach it forgot to tune."""
    runway = provider.get_runway("ZZZZ", "09")
    assert runway is not None
    assert runway.ils is not None
    assert runway.ils.frequency_khz == 109_500
    assert runway.ils.glideslope_deg == pytest.approx(3.0)


def test_get_ils_agrees_with_the_runway(provider: NavdataProvider) -> None:
    runway = provider.get_runway("ZZZZ", "09")
    assert runway is not None
    assert provider.get_ils("ZZZZ", "09") == runway.ils


def test_a_runway_without_an_ils_reports_none(provider: NavdataProvider) -> None:
    assert provider.get_ils("ZZZZ", "27") is None


# --------------------------------------------------------------------------
# Parking
# --------------------------------------------------------------------------


def test_parking_is_one_model_filtered_by_kind(provider: NavdataProvider) -> None:
    assert {s.name for s in provider.get_parking("ZZZZ")} == {"R32", "GA1"}
    assert {s.name for s in provider.get_parking("ZZZZ", kind="gate")} == {"R32"}
    assert provider.get_parking("ZZZZ", kind="hangar") == []


# --------------------------------------------------------------------------
# Navaids and fixes
# --------------------------------------------------------------------------


def test_navaid_lookup_returns_a_list(provider: NavdataProvider) -> None:
    """Idents are not globally unique, so the singular case is still a list."""
    assert [n.ident for n in provider.get_navaids("ZUL")] == ["ZUL"]


def test_navaids_can_be_filtered_by_kind(provider: NavdataProvider) -> None:
    assert provider.get_navaids("ZUL", kinds=NDB_ONLY) == []
    assert len(provider.get_navaids("ZUL", kinds=VOR_DME_ONLY)) == 1


def test_an_ndb_is_tuned_on_the_adf(provider: NavdataProvider) -> None:
    """The frequency alone would be a trap: 380 kHz fails nav1_freq_khz validation."""
    ndb = provider.get_navaids("ZB")[0]
    assert ndb.tunable_radio == "adf"
    assert ndb.frequency_khz == 380


def test_a_glideslope_is_not_tunable(provider: NavdataProvider) -> None:
    glideslope = provider.get_navaids("IZZZ", kinds=GLIDESLOPE_ONLY)[0]
    assert glideslope.tunable_radio is None


def test_a_vhf_navaid_shares_the_units_of_aircraft_setup(provider: NavdataProvider) -> None:
    vor = provider.get_navaids("ZUL")[0]
    assert vor.frequency_khz is not None
    assert 108_000 <= vor.frequency_khz <= 117_950


def test_navaids_near_is_bounded_and_sorted(provider: NavdataProvider) -> None:
    near = provider.navaids_near(AIRPORT.position, radius_nm=100.0)
    assert near
    distances = [distance_and_bearing(AIRPORT.position, n.position)[0] for n in near]
    assert distances == sorted(distances)


def test_terminal_and_enroute_fixes_share_an_ident(provider: NavdataProvider) -> None:
    """The terminal scope is what makes half a SID's legs resolvable at all."""
    assert len(provider.get_fixes("ZOXOL")) == 2
    terminal = provider.get_fixes("ZOXOL", terminal_airport="ZZZZ")
    assert len(terminal) == 1
    assert terminal[0].terminal_airport_icao == "ZZZZ"


def test_resolve_fix_honours_the_terminal_scope(provider: NavdataProvider) -> None:
    """P/C is a terminal waypoint; E/A is the enroute one with the same name."""
    terminal = provider.resolve_fix(
        FixRef(ident="ZOXOL", region_code="LE", section="P", subsection="C", airport_icao="ZZZZ")
    )
    enroute = provider.resolve_fix(
        FixRef(ident="ZOXOL", region_code="LE", section="E", subsection="A")
    )
    assert terminal is not None
    assert enroute is not None
    assert terminal.position != enroute.position
    assert terminal.position == TERMINAL_FIX.position
    assert enroute.position == ENROUTE_FIX.position


def test_resolve_fix_reaches_navaids_and_runways(provider: NavdataProvider) -> None:
    vor = provider.resolve_fix(FixRef(ident="ZUL", region_code="LE", section="D", subsection=""))
    assert vor is not None
    assert vor.kind == "vor"

    runway = provider.resolve_fix(
        FixRef(ident="09", region_code="LE", section="P", subsection="G", airport_icao="ZZZZ")
    )
    assert runway is not None
    assert runway.kind == "runway"
    assert runway.position == THRESHOLD


def test_resolve_fix_returns_none_when_nothing_matches(provider: NavdataProvider) -> None:
    assert (
        provider.resolve_fix(FixRef(ident="NOPE", region_code="LE", section="E", subsection="A"))
        is None
    )


# --------------------------------------------------------------------------
# Holds
# --------------------------------------------------------------------------


def test_holds_are_filtered_by_fix_and_airport(provider: NavdataProvider) -> None:
    assert len(provider.get_holds(fix_ident="ZUL")) == 1
    assert len(provider.get_holds(airport_icao="ZZZZ")) == 1
    assert provider.get_holds(fix_ident="NOPE") == []


def test_a_hold_has_exactly_one_leg_measure(provider: NavdataProvider) -> None:
    """Published holds carry either a time or a distance, never both and never neither."""
    for hold in provider.get_holds():
        assert (hold.leg_time_min is None) != (hold.leg_length_nm is None)


# --------------------------------------------------------------------------
# Procedures
# --------------------------------------------------------------------------


def test_procedures_are_listed_as_summaries(provider: NavdataProvider) -> None:
    summaries = provider.get_procedures("ZZZZ")
    assert {s.ident for s in summaries} == {"ZULU1A", "I09"}


def test_procedures_can_be_filtered_by_kind(provider: NavdataProvider) -> None:
    assert {s.ident for s in provider.get_procedures("ZZZZ", kind="sid")} == {"ZULU1A"}
    assert {s.ident for s in provider.get_procedures("ZZZZ", kind="approach")} == {"I09"}


def test_summary_counts_match_the_full_procedure(provider: NavdataProvider) -> None:
    summary = next(s for s in provider.get_procedures("ZZZZ") if s.ident == "ZULU1A")
    procedure = provider.get_procedure("ZZZZ", "sid", "ZULU1A")
    assert procedure is not None
    assert summary.leg_count == len(procedure.legs)
    assert summary.positionable_leg_count == sum(1 for leg in procedure.legs if leg.is_positionable)


def test_unpositionable_legs_are_returned_not_hidden(provider: NavdataProvider) -> None:
    """An instructor reading a SID needs to see the climb leg — it is just not offered."""
    procedure = provider.get_procedure("ZZZZ", "sid", "ZULU1A")
    assert procedure is not None
    climb = next(leg for leg in procedure.legs if leg.path_terminator == "CA")
    assert climb.is_positionable is False
    assert climb.unpositionable_reason


def test_every_positionable_leg_carries_a_resolved_fix(provider: NavdataProvider) -> None:
    """The invariant the whole Position Manager turns on."""
    for summary in provider.get_procedures("ZZZZ"):
        procedure = provider.get_procedure(
            summary.airport_icao, summary.kind, summary.ident, summary.transition
        )
        assert procedure is not None
        for leg in procedure.legs:
            if leg.is_positionable:
                assert leg.fix is not None, f"{summary.ident} leg {leg.sequence} has no fix"
            else:
                assert leg.unpositionable_reason, (
                    f"{summary.ident} leg {leg.sequence} is not positionable and does not say why"
                )


def test_a_procedure_is_fetched_by_its_transition(provider: NavdataProvider) -> None:
    assert provider.get_procedure("ZZZZ", "approach", "I09", "ZOXOL") is not None
    assert provider.get_procedure("ZZZZ", "approach", "I09", "NOSUCH") is None
