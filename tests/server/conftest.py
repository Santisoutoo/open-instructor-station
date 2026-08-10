"""A hand-written navigation world for the Position Manager routes.

**Nothing here comes from a real navdata file.** Hard rule 4 forbids committing
``apt.dat``, ``earth_*.dat`` or any CIFP extract, so this is a deliberately tiny
invented airport with round numbers — which is also what makes the geometry
assertions readable: a runway on a true bearing of 000° at 1000 ft means "10 NM
final" is "10 NM due south at 4184.4 ft".
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import server.deps
from core.models import GeoPosition, Ils, Runway
from core.navdata.in_memory import InMemoryNavdataProvider
from core.navdata.models import (
    Airport,
    AltitudeConstraint,
    Fix,
    Hold,
    Navaid,
    ParkingStand,
    Procedure,
    ProcedureLeg,
    SpeedConstraint,
    Waypoint,
)
from server.app import create_app
from server.deps import reset_navdata

#: The invented airport. "ZZZZ" is the ICAO code reserved for "no code
#: assigned", so it can never collide with a real one.
AIRPORT = Airport(
    icao="ZZZZ",
    iata="ZZZ",
    name="Testfield International",
    city="Testville",
    country="Nowhere",
    region_code="ZZ",
    position=GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=1000.0),
    elevation_ft=1000.0,
    magnetic_variation_deg=-2.0,
    runway_count=2,
    longest_runway_m=3000.0,
    has_procedures=True,
)

#: A second airport, so search ranking has something to rank against.
OTHER_AIRPORT = Airport(
    icao="ZZZA",
    name="Testfield Grass Strip",
    position=GeoPosition(latitude=41.0, longitude=-3.0, altitude_ft=500.0),
    elevation_ft=500.0,
    runway_count=1,
    longest_runway_m=600.0,
    has_procedures=False,
)

ILS_36 = Ils(
    airport_icao="ZZZZ",
    runway_ident="36",
    localizer_ident="IZZZ",
    frequency_khz=110300,
    localizer_position=GeoPosition(latitude=40.027, longitude=-3.0, altitude_ft=1000.0),
    localizer_true_deg=0.0,
    localizer_mag_deg=2.0,
    glideslope_deg=3.0,
    category="I",
)

#: Runway 36: due true north, so "left of the runway" is "to the west" and the
#: extended centreline runs due south. Every pattern assertion reads by eye.
RUNWAY_36 = Runway(
    airport_icao="ZZZZ",
    ident="36",
    threshold=GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=1000.0),
    true_bearing_deg=0.0,
    length_m=3000.0,
    elevation_ft=1000.0,
    opposite_ident="18",
    ils=ILS_36,
)

RUNWAY_18 = Runway(
    airport_icao="ZZZZ",
    ident="18",
    threshold=GeoPosition(latitude=40.027, longitude=-3.0, altitude_ft=1000.0),
    true_bearing_deg=180.0,
    length_m=3000.0,
    elevation_ft=1000.0,
    opposite_ident="36",
)

STAND = ParkingStand(
    airport_icao="ZZZZ",
    name="R32",
    position=GeoPosition(latitude=40.005, longitude=-3.002, altitude_ft=1000.0),
    heading_true_deg=270.0,
    kind="gate",
)

#: A VOR on the field, and a second navaid **with the same identifier** in
#: another region. Navaid idents are not globally unique — that is the whole
#: reason ``get_navaids`` returns a list — so the fixture has to contain a
#: collision or the route's list-ness is never actually exercised.
VOR_ZZT = Navaid(
    ident="ZZT",
    kind="vor_dme",
    name="Testfield VOR",
    position=GeoPosition(latitude=40.01, longitude=-3.0, altitude_ft=1000.0),
    frequency_khz=113_700,
    range_nm=130.0,
    region_code="ZZ",
)

VOR_ZZT_ELSEWHERE = Navaid(
    ident="ZZT",
    kind="vor",
    name="Faraway VOR",
    position=GeoPosition(latitude=10.0, longitude=10.0, altitude_ft=0.0),
    frequency_khz=115_200,
    region_code="YY",
)

NDB_ZZN = Navaid(
    ident="ZZN",
    kind="ndb",
    name="Testfield NDB",
    position=GeoPosition(latitude=39.98, longitude=-3.0, altitude_ft=1000.0),
    frequency_khz=380,
    region_code="ZZ",
    tunable_radio="adf",
)

FIX_GOXOL = Fix(
    ident="GOXOL",
    position=GeoPosition(latitude=40.5, longitude=-3.0),
    region_code="ZZ",
)

HOLD_GOXOL = Hold(
    fix=Waypoint(ident="GOXOL", kind="fix", position=FIX_GOXOL.position, region_code="ZZ"),
    inbound_course_mag_deg=180.0,
    turn_direction="R",
    leg_time_min=1.0,
    min_altitude_ft=7000.0,
    speed_kt=210.0,
    airport_icao="ZZZZ",
)

#: A SID with one positionable leg and one that is not, which is the pair the
#: UI has to render differently.
SID = Procedure(
    airport_icao="ZZZZ",
    kind="sid",
    ident="TEST1A",
    runway_idents=("36",),
    legs=(
        ProcedureLeg(
            sequence=10,
            path_terminator="CA",
            is_positionable=False,
            unpositionable_reason=(
                "A CA leg ends at an altitude, not at a fix: it has no defensible coordinate."
            ),
        ),
        ProcedureLeg(
            sequence=20,
            path_terminator="TF",
            is_positionable=True,
            fix=Waypoint(ident="GOXOL", kind="fix", position=FIX_GOXOL.position, region_code="ZZ"),
            altitude=AltitudeConstraint(descriptor="+", min_ft=6000.0),
            speed=SpeedConstraint(descriptor="-", max_kt=250.0),
        ),
        ProcedureLeg(
            sequence=30,
            path_terminator="TF",
            is_positionable=True,
            fix=Waypoint(
                ident="NOALT",
                kind="fix",
                position=GeoPosition(latitude=41.0, longitude=-3.0),
                region_code="ZZ",
            ),
        ),
    ),
)


def build_provider() -> InMemoryNavdataProvider:
    """The whole invented world, as a provider."""
    return InMemoryNavdataProvider(
        airports=[AIRPORT, OTHER_AIRPORT],
        runways=[RUNWAY_36, RUNWAY_18],
        parking=[STAND],
        navaids=[VOR_ZZT, VOR_ZZT_ELSEWHERE, NDB_ZZN],
        fixes=[FIX_GOXOL],
        holds=[HOLD_GOXOL],
        procedures=[SID],
    )


@pytest.fixture
def navdata(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryNavdataProvider]:
    """Serve the invented world from ``get_navdata()`` for the duration of a test."""
    provider = build_provider()
    monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
    reset_navdata()
    yield provider
    reset_navdata()


@pytest.fixture
def client(navdata: InMemoryNavdataProvider) -> TestClient:
    """A test client whose navdata is the invented world."""
    del navdata  # ordering dependency only
    return TestClient(create_app())
