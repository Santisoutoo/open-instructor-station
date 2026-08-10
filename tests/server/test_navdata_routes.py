"""``/api/navdata/*`` against the hand-written world in ``conftest.py``."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.deps
from core.navdata.in_memory import InMemoryNavdataProvider
from core.navdata.models import NavdataStatus
from core.navdata.provider import NavdataUnavailable
from server.app import create_app
from server.deps import reset_navdata
from server.navdata_routes import (
    BUILDING_RETRY_AFTER_S,
    NAVDATA_UNAVAILABLE_STATUS,
    UNAVAILABLE_RETRY_AFTER_S,
)


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
            response = client.get("/api/navdata/airports", params={"q": "Testfield"})
        assert response.status_code == 200
        assert [row["icao"] for row in response.json()] == ["ZZZZ", "ZZZA"]

    def test_search_respects_the_limit(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/airports", params={"q": "Testfield", "limit": 1})
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_an_empty_query_is_rejected_rather_than_returning_the_world(
        self, client: TestClient
    ) -> None:
        with client:
            response = client.get("/api/navdata/airports", params={"q": ""})
        assert response.status_code == 422

    def test_the_search_parameter_is_q_as_the_design_specifies(self, client: TestClient) -> None:
        """``?q=``, not ``?query=`` — pinned because the UI client is generated from it.

        The name is part of the published surface, so a silent drift back to
        ``query`` would compile on both sides and only fail at runtime.
        """
        with client:
            wrong_name = client.get("/api/navdata/airports", params={"query": "Testfield"})
        assert wrong_name.status_code == 422

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


class TestNavaids:
    """``GET /api/navdata/navaids`` — two query forms on one path (design §12)."""

    def test_by_ident_returns_every_match_because_idents_collide(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/navaids", params={"ident": "ZZT"})
        assert response.status_code == 200
        assert [row["region_code"] for row in response.json()] == ["YY", "ZZ"]

    def test_a_region_disambiguates(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/navdata/navaids", params={"ident": "ZZT", "region": "ZZ"})
        assert [row["name"] for row in response.json()] == ["Testfield VOR"]

    def test_an_unknown_ident_is_an_empty_list_not_a_404(self, client: TestClient) -> None:
        """Absent is ``[]`` on a list route: the provider never raises for not-found."""
        with client:
            response = client.get("/api/navdata/navaids", params={"ident": "NOPE"})
        assert response.status_code == 200
        assert response.json() == []

    def test_near_a_point_returns_the_local_ones_nearest_first(self, client: TestClient) -> None:
        with client:
            response = client.get(
                "/api/navdata/navaids",
                params={"lat": 40.0, "lon": -3.0, "radius_nm": 5.0},
            )
        assert response.status_code == 200
        # The VOR is 0.01° north of the point, the NDB 0.02° south of it, and
        # the far-away VOR sharing the ident is 1000 NM away and excluded.
        assert [row["ident"] for row in response.json()] == ["ZZT", "ZZN"]

    def test_near_filters_by_kind(self, client: TestClient) -> None:
        """An instructor tuning NAV1 must not be offered an NDB."""
        with client:
            response = client.get(
                "/api/navdata/navaids",
                params={"lat": 40.0, "lon": -3.0, "radius_nm": 5.0, "kinds": ["vor_dme"]},
            )
        assert [row["ident"] for row in response.json()] == ["ZZT"]

    def test_the_ndb_is_marked_for_the_adf_and_not_the_nav_radio(self, client: TestClient) -> None:
        """The three-state field is what stops an NDB reaching ``nav1_freq_khz``."""
        with client:
            response = client.get("/api/navdata/navaids", params={"ident": "ZZN"})
        assert response.json()[0]["tunable_radio"] == "adf"

    def test_neither_form_is_rejected_rather_than_returning_the_world(
        self, client: TestClient
    ) -> None:
        with client:
            response = client.get("/api/navdata/navaids")
        assert response.status_code == 422

    def test_both_forms_at_once_is_rejected_rather_than_guessing(self, client: TestClient) -> None:
        with client:
            response = client.get(
                "/api/navdata/navaids", params={"ident": "ZZT", "lat": 40.0, "lon": -3.0}
            )
        assert response.status_code == 422


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
    """A broken provider answers 503 with its reason — never a 500.

    Design §12 pins the whole answer, not only the status code: a
    ``Retry-After`` whose value distinguishes "wait, it is building" from "a
    human has to act", and ``status()`` in the body so a UI that raced the build
    gets state instead of an opaque error.
    """

    @staticmethod
    def _broken_client(monkeypatch: pytest.MonkeyPatch, state: str, reason: str) -> TestClient:
        class BrokenProvider(InMemoryNavdataProvider):
            def status(self) -> NavdataStatus:
                return super().status().model_copy(update={"state": state, "reason": reason})

            def search_airports(self, query: str, *, limit: int = 20) -> list:  # type: ignore[type-arg]
                raise NavdataUnavailable("in_memory", reason)

        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: BrokenProvider())
        reset_navdata()
        return TestClient(create_app(), raise_server_exceptions=False)

    @pytest.fixture
    def broken_client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        return self._broken_client(monkeypatch, "unavailable", "The index has not been built.")

    @pytest.fixture
    def building_client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        return self._broken_client(monkeypatch, "building", "The index is being built.")

    def test_a_query_against_a_broken_provider_is_503(self, broken_client: TestClient) -> None:
        with broken_client:
            response = broken_client.get("/api/navdata/airports", params={"q": "ZZ"})
        assert response.status_code == NAVDATA_UNAVAILABLE_STATUS
        assert "not been built" in response.json()["detail"]

    def test_the_body_carries_the_status_so_a_racing_client_learns_the_state(
        self, broken_client: TestClient
    ) -> None:
        with broken_client:
            response = broken_client.get("/api/navdata/airports", params={"q": "ZZ"})
        status = response.json()["status"]
        assert status["state"] == "unavailable"
        assert status["provider"] == "in_memory"

    def test_an_unavailable_provider_asks_for_a_long_wait(self, broken_client: TestClient) -> None:
        """A human has to act, so retrying in five seconds only burns battery."""
        with broken_client:
            response = broken_client.get("/api/navdata/airports", params={"q": "ZZ"})
        assert response.headers["Retry-After"] == str(UNAVAILABLE_RETRY_AFTER_S)

    def test_a_building_provider_asks_for_a_short_wait(self, building_client: TestClient) -> None:
        """The build finishes on its own; the client only has to come back."""
        with building_client:
            response = building_client.get("/api/navdata/airports", params={"q": "ZZ"})
        assert response.status_code == NAVDATA_UNAVAILABLE_STATUS
        assert response.headers["Retry-After"] == str(BUILDING_RETRY_AFTER_S)
        assert response.json()["status"]["state"] == "building"
