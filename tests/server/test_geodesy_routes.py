"""``/api/geodesy/measure`` — the Instructor Map's one new endpoint.

instructor-map.md (§2.1, §8.2): the route is a *faithful wrapper* around
``core.geodesy.distance_and_bearing`` and nothing more, so the assertions here
are the same golden pair the core suite already proves
(``tests/core/test_geodesy.py``): 25 NM at 137° true from Madrid measures back
as exactly (25.0 NM, 137.0°). Targets are computed with ``core.geodesy`` in the
test — never hard-coded coordinates — so a solver change that stays
self-consistent cannot silently invalidate the fixture.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.geodesy import distance_and_bearing, point_at_distance_and_bearing
from core.models import GeoPosition

#: Same origin as the core geodesy suite's golden values (§8.1 cites the pair).
MADRID = GeoPosition(latitude=40.4168, longitude=-3.7038)


def _measure(client: TestClient, a: GeoPosition, b: GeoPosition) -> dict[str, Any]:
    with client:
        response = client.get(
            "/api/geodesy/measure",
            params={
                "lat1": a.latitude,
                "lon1": a.longitude,
                "lat2": b.latitude,
                "lon2": b.longitude,
            },
        )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


class TestMeasure:
    def test_returns_the_core_golden_pair(self, client: TestClient) -> None:
        """25 NM at 137° true from Madrid reads back as (25.0 NM, 137.0°)."""
        target = point_at_distance_and_bearing(MADRID, 25.0, 137.0)
        body = _measure(client, MADRID, target)
        assert body["distance_nm"] == pytest.approx(25.0, abs=1e-6)
        assert body["initial_bearing_true_deg"] == pytest.approx(137.0, abs=1e-6)

    def test_swapping_the_points_returns_the_reciprocal_bearing(self, client: TestClient) -> None:
        """Mirrors ``test_distance_is_symmetric`` in the core suite.

        The distance is identical in both directions. The back-bearing is the
        reciprocal of 137° only up to meridian convergence (~0.24° over 25 NM
        at this latitude), so the exact expectation is what ``core.geodesy``
        itself computes for the swapped pair — the faithful-wrapper check —
        with the reciprocal asserted to a convergence-sized tolerance on top.
        """
        target = point_at_distance_and_bearing(MADRID, 25.0, 137.0)
        forward = _measure(client, MADRID, target)
        backward = _measure(client, target, MADRID)

        assert backward["distance_nm"] == pytest.approx(forward["distance_nm"], abs=1e-9)

        expected_nm, expected_bearing = distance_and_bearing(target, MADRID)
        assert backward["distance_nm"] == pytest.approx(expected_nm, abs=1e-9)
        assert backward["initial_bearing_true_deg"] == pytest.approx(expected_bearing, abs=1e-9)
        assert backward["initial_bearing_true_deg"] == pytest.approx(
            (137.0 + 180.0) % 360.0, abs=0.5
        )

    def test_out_of_range_latitude_is_422(self, client: TestClient) -> None:
        """lat1=91 violates ``Query(ge=-90, le=90)`` — FastAPI's own 422."""
        with client:
            response = client.get(
                "/api/geodesy/measure",
                params={"lat1": 91.0, "lon1": 0.0, "lat2": 0.0, "lon2": 0.0},
            )
        assert response.status_code == 422
