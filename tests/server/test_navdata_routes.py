"""``/api/navdata/*`` against the hand-written world in ``conftest.py``."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.deps
from core.navdata.in_memory import InMemoryNavdataProvider
from core.navdata.provider import NavdataUnavailable
from server.app import create_app
from server.deps import reset_navdata
from server.navdata_routes import NAVDATA_UNAVAILABLE_STATUS


class TestStatus:
    def test_it_reports_a_ready_provider(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/status")
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "ready"
        assert body["provider"] == "in_memory"
        assert body["airport_count"] == 2

    def test_index_is_idempotent_and_answers_with_the_status(self, client: TestClient) -> None:
        with client:
            first = client.post("/api/navdata/index")
            second = client.post("/api/navdata/index")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["state"] == second.json()["state"] == "ready"


class TestAirports:
    def test_search_ranks_the_bigger_field_first(self, client: TestClient) -> None:
        """An instructor typing a partial name wants the airport, not the strip."""
        with client:
            response = client.get("/api/navdata/airports", params={"query": "Testfield"})
        assert response.status_code == 200
        assert [row["icao"] for row in response.json()] == ["ZZZZ", "ZZZA"]

    def test_search_respects_the_limit(self, client: TestClient) -> None:
        with client:
            response = client.get(
                "/api/navdata/airports", params={"query": "Testfield", "limit": 1}
            )
        assert len(response.json()) == 1

    def test_an_empty_query_is_rejected_rather_than_returning_the_world(
        self, client: TestClient
    ) -> None:
        with client:
            response = client.get("/api/navdata/airports", params={"query": ""})
        assert response.status_code == 422

    def test_one_airport(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/ZZZZ")
        assert response.status_code == 200
        assert response.json()["name"] == "Testfield International"

    def test_an_unknown_airport_is_404_not_an_error(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/XXXX")
        assert response.status_code == 404
        assert "XXXX" in response.json()["detail"]

    def test_near_finds_by_position(self, client: TestClient) -> None:
        with client:
            response = client.get(
                "/api/navdata/airports/near",
                params={"lat": 40.0, "lon": -3.0, "radius_nm": 10.0},
            )
        assert response.status_code == 200
        assert [row["icao"] for row in response.json()] == ["ZZZZ"]

    def test_near_is_not_shadowed_by_the_icao_route(self, client: TestClient) -> None:
        """``/airports/near`` must be matched before ``/airports/{icao}``."""
        with client:
            response = client.get("/api/navdata/airports/near", params={"lat": 0.0, "lon": 0.0})
        assert response.status_code == 200
        assert response.json() == []


class TestRunwaysAndIls:
    def test_both_ends_are_returned(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/ZZZZ/runways")
        assert response.status_code == 200
        assert [row["ident"] for row in response.json()] == ["18", "36"]

    def test_the_ils_of_one_end(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/ZZZZ/runways/36/ils")
        assert response.status_code == 200
        assert response.json()["frequency_khz"] == 110300

    def test_a_runway_without_an_ils_is_404(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/ZZZZ/runways/18/ils")
        assert response.status_code == 404

    def test_an_unknown_airport_has_no_runways_rather_than_failing(
        self, client: TestClient
    ) -> None:
        with client:
            response = client.get("/api/navdata/airports/XXXX/runways")
        assert response.status_code == 200
        assert response.json() == []


class TestParkingAndProcedures:
    def test_parking(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/ZZZZ/parking")
        assert [row["name"] for row in response.json()] == ["R32"]

    def test_parking_filters_by_kind(self, client: TestClient) -> None:
        with client:
            gates = client.get("/api/navdata/airports/ZZZZ/parking", params={"kind": "gate"})
            hangars = client.get("/api/navdata/airports/ZZZZ/parking", params={"kind": "hangar"})
        assert len(gates.json()) == 1
        assert hangars.json() == []

    def test_procedure_summaries(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/ZZZZ/procedures")
        assert response.status_code == 200
        summary = response.json()[0]
        assert summary["ident"] == "TEST1A"
        assert summary["leg_count"] == 3
        assert summary["positionable_leg_count"] == 2

    def test_one_procedure_returns_unpositionable_legs_too(self, client: TestClient) -> None:
        """An instructor reading a SID needs to see the climb leg it cannot place on."""
        with client:
            response = client.get("/api/navdata/airports/ZZZZ/procedures/sid/TEST1A")
        assert response.status_code == 200
        legs = response.json()["legs"]
        assert len(legs) == 3
        climb = next(leg for leg in legs if leg["path_terminator"] == "CA")
        assert climb["is_positionable"] is False
        assert "no defensible coordinate" in climb["unpositionable_reason"]

    def test_an_unknown_procedure_is_404(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports/ZZZZ/procedures/sid/NOPE1A")
        assert response.status_code == 404


class TestFixesAndHolds:
    def test_fixes_by_ident(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/fixes", params={"ident": "GOXOL"})
        assert [row["ident"] for row in response.json()] == ["GOXOL"]

    def test_holds_by_fix(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/holds", params={"fix_ident": "GOXOL"})
        assert response.status_code == 200
        hold = response.json()[0]
        assert hold["inbound_course_mag_deg"] == 180.0
        assert hold["turn_direction"] == "R"


class TestUnavailableProvider:
    """A broken provider answers 503 with its reason — never a 500."""

    @pytest.fixture
    def broken_client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        class BrokenProvider(InMemoryNavdataProvider):
            def search_airports(self, query: str, *, limit: int = 20) -> list:  # type: ignore[type-arg]
                raise NavdataUnavailable("in_memory", "The index has not been built.")

        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: BrokenProvider())
        reset_navdata()
        return TestClient(create_app(), raise_server_exceptions=False)

    def test_a_query_against_a_broken_provider_is_503(self, broken_client: TestClient) -> None:
        with broken_client:
            response = broken_client.get("/api/navdata/airports", params={"query": "ZZ"})
        assert response.status_code == NAVDATA_UNAVAILABLE_STATUS
        assert "not been built" in response.json()["detail"]
