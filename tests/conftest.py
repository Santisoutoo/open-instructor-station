"""Shared fixtures."""

from collections.abc import Iterator

import pytest

from core.models import GeoPosition, Runway
from server.deps import reset_adapter

#: A synthetic runway used across the geodesy tests: LEMD 32L-ish, pointing
#: north-west, at 2000 ft elevation so altitude maths is not masked by zero.
SAMPLE_RUNWAY = Runway(
    airport_icao="LEMD",
    ident="32L",
    threshold=GeoPosition(latitude=40.4700, longitude=-3.5700, altitude_ft=2000.0),
    true_bearing_deg=320.0,
    length_m=3500.0,
    elevation_ft=2000.0,
)

#: A runway pointing due true north, which makes traffic-pattern geometry
#: readable by eye: "left of the runway" is simply "to the west".
NORTH_RUNWAY = Runway(
    airport_icao="TEST",
    ident="36",
    threshold=GeoPosition(latitude=40.0000, longitude=-3.0000, altitude_ft=1000.0),
    true_bearing_deg=0.0,
    length_m=3000.0,
    elevation_ft=1000.0,
)


@pytest.fixture(autouse=True)
def _isolated_settings() -> Iterator[None]:
    """Make sure no test inherits another test's cached adapter or settings."""
    reset_adapter()
    yield
    reset_adapter()
