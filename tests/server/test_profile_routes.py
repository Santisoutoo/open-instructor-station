"""``/api/profiles/*`` — CRUD, import/export, and the two degradation cases
the feature spec calls out by name (docs/designs/training-profiles.md §8.3).

Against ``TestClient`` + ``FakeSimAdapter``, a ``tmp_path``-backed
``ProfileStore`` (dependency override, the same pattern
``reset_navdata()``/``reset_adapter()`` already establish) and the ``ZZZZ``
fixture world from ``tests/server/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.failures import InjectFailureRequest
from core.navdata.in_memory import InMemoryNavdataProvider
from core.placements import RunwayThresholdPlacementRequest
from core.profiles.store import ProfileStore
from core.scenarios.models import ScenarioDocument, ScenarioFailuresBlock
from core.sim_adapter import Capabilities
from core.weather.models import WeatherRequest
from server.app import create_app
from server.deps import reset_adapter, reset_profile_store

# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class _NoFailuresAdapter(FakeSimAdapter):
    """Every capability except ``can_inject_failures`` — the failures-manager.md pattern."""

    @property
    def name(self) -> str:
        return "no-failures"

    @property
    def capabilities(self) -> Capabilities:
        return super().capabilities.model_copy(update={"can_inject_failures": False})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def profile_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ProfileStore]:
    store = ProfileStore(tmp_path / "profiles")
    monkeypatch.setattr(server.deps, "_build_profile_store", lambda _settings: store)
    reset_profile_store()
    yield store
    reset_profile_store()


@pytest.fixture
def client(navdata: InMemoryNavdataProvider, profile_store: ProfileStore) -> Iterator[TestClient]:
    del navdata, profile_store  # ordering dependency only
    yield TestClient(create_app())


@pytest.fixture
def no_failures_client(
    navdata: InMemoryNavdataProvider,
    profile_store: ProfileStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    del navdata, profile_store  # ordering dependency only
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _NoFailuresAdapter())
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _weather_only_draft(name: str = "Weather only") -> dict[str, object]:
    scenario = ScenarioDocument(
        name=name,
        description="Just weather.",
        weather=WeatherRequest(preset="cavok"),
    )
    return {
        "name": name,
        "description": "A test profile.",
        "author": "Instructor",
        "scenario": scenario.model_dump(mode="json"),
    }


def _degraded_draft() -> dict[str, object]:
    """A profile whose position references an airport absent from the ZZZZ world."""
    scenario = ScenarioDocument(
        name="Degraded profile",
        description="Position cannot resolve; weather and failures still should.",
        position=RunwayThresholdPlacementRequest(
            type="runway_threshold", airport_icao="ZZZQ", runway_ident="09"
        ),
        weather=WeatherRequest(preset="cavok"),
        failures=ScenarioFailuresBlock(
            immediate=(InjectFailureRequest(failure_id="airframe.smoke"),)
        ),
    )
    return {
        "name": "Degraded profile",
        "description": "",
        "author": None,
        "scenario": scenario.model_dump(mode="json"),
    }


def _failures_only_draft() -> dict[str, object]:
    scenario = ScenarioDocument(
        name="Smoke drill",
        description="Failures only, no position or weather.",
        failures=ScenarioFailuresBlock(
            immediate=(InjectFailureRequest(failure_id="airframe.smoke"),)
        ),
    )
    return {
        "name": "Smoke drill",
        "description": "",
        "author": None,
        "scenario": scenario.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCrud:
    def test_full_round_trip(self, client: TestClient) -> None:
        with client:
            created = client.post("/api/profiles", json=_weather_only_draft("Original"))
            assert created.status_code == 200, created.text
            profile_id = created.json()["profile_id"]

            listing = client.get("/api/profiles")
            assert profile_id in [row["profile_id"] for row in listing.json()]

            fetched = client.get(f"/api/profiles/{profile_id}")
            assert fetched.status_code == 200
            assert fetched.json()["name"] == "Original"

            replaced = client.put(
                f"/api/profiles/{profile_id}", json=_weather_only_draft("Renamed")
            )
            assert replaced.status_code == 200
            assert replaced.json()["name"] == "Renamed"
            assert replaced.json()["profile_id"] == profile_id

            deleted = client.delete(f"/api/profiles/{profile_id}")
            assert deleted.status_code == 204

            after_delete = client.get(f"/api/profiles/{profile_id}")
        assert after_delete.status_code == 404
        assert after_delete.json()["detail"] == f"No training profile {profile_id!r}."

    def test_delete_of_unknown_id_names_may_already_be_deleted(self, client: TestClient) -> None:
        with client:
            response = client.delete("/api/profiles/" + "0" * 32)
        assert response.status_code == 404
        assert "may already be deleted" in response.json()["detail"]

    def test_put_on_unknown_id_is_404_and_never_creates(self, client: TestClient) -> None:
        unknown_id = "0" * 32
        with client:
            response = client.put(f"/api/profiles/{unknown_id}", json=_weather_only_draft())
            assert response.status_code == 404
            listing = client.get("/api/profiles")
        assert listing.json() == []

    def test_create_with_a_malformed_body_is_422(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/profiles", json={"name": "", "scenario": {"description": "no name"}}
            )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------


class TestImportExport:
    def test_round_trip_with_a_fresh_id(self, client: TestClient) -> None:
        with client:
            created = client.post("/api/profiles", json=_weather_only_draft("Exported"))
            profile_id = created.json()["profile_id"]

            exported = client.get(f"/api/profiles/{profile_id}/export")
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("application/json")
            assert "attachment" in exported.headers["content-disposition"]

            imported = client.post(
                "/api/profiles/import",
                files={"file": ("profile.json", exported.content, "application/json")},
            )
        assert imported.status_code == 200, imported.text
        body = imported.json()
        assert body["profile_id"] != profile_id
        assert body["name"] == "Exported"

    def test_export_of_unknown_id_is_404(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/profiles/" + "0" * 32 + "/export")
        assert response.status_code == 404
        assert "may already be deleted" in response.json()["detail"]

    def test_import_of_malformed_upload_is_422(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/profiles/import",
                files={"file": ("bad.json", b"{not valid json", "application/json")},
            )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Apply — the two degradation cases (§8.3)
# ---------------------------------------------------------------------------


class TestApply:
    def test_unknown_profile_id_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/profiles/" + "0" * 32 + "/apply")
        assert response.status_code == 404

    def test_happy_path_every_component_applies(self, client: TestClient) -> None:
        with client:
            created = client.post("/api/profiles", json=_weather_only_draft())
            profile_id = created.json()["profile_id"]
            response = client.post(f"/api/profiles/{profile_id}/apply")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["degraded"] is False
        assert body["weather"]["attempted"] is True
        assert body["weather"]["applied"] is True
        assert body["weather"]["result"]["applied"]["visibility_m"] == pytest.approx(20_000.0)
        assert body["position"]["attempted"] is False
        assert body["failures"] == []

    def test_unresolvable_placement_degrades_but_applies_the_rest(self, client: TestClient) -> None:
        with client:
            created = client.post("/api/profiles", json=_degraded_draft())
            profile_id = created.json()["profile_id"]
            response = client.post(f"/api/profiles/{profile_id}/apply")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["degraded"] is True
        assert body["position"]["applied"] is False
        assert "ZZZQ" in body["position"]["reason"]
        assert body["weather"]["applied"] is True
        assert body["failures"][0]["applied"] is True

    def test_capability_refusal_degrades_but_applies_the_rest(
        self, no_failures_client: TestClient
    ) -> None:
        with no_failures_client:
            created = no_failures_client.post("/api/profiles", json=_degraded_draft())
            profile_id = created.json()["profile_id"]
            response = no_failures_client.post(f"/api/profiles/{profile_id}/apply")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["degraded"] is True
        # The position step still fails on its own terms (unresolvable navdata) —
        # the capability refusal is proven on the failures entry, which does not
        # depend on navdata at all.
        assert body["failures"][0]["applied"] is False
        assert "can_inject_failures" in body["failures"][0]["reason"]
        assert body["weather"]["applied"] is True

    def test_capability_refusal_alone_still_degrades(self, no_failures_client: TestClient) -> None:
        with no_failures_client:
            created = no_failures_client.post("/api/profiles", json=_failures_only_draft())
            profile_id = created.json()["profile_id"]
            response = no_failures_client.post(f"/api/profiles/{profile_id}/apply")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["degraded"] is True
        assert body["position"]["attempted"] is False
        assert body["weather"]["attempted"] is False
        assert body["failures"][0]["applied"] is False
        assert "can_inject_failures" in body["failures"][0]["reason"]


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_openapi_exposes_the_profiles_surface(client: TestClient) -> None:
    """``npm run generate:api`` reads this; the panel's types come from nowhere else."""
    with client:
        response = client.get("/openapi.json")
    paths = response.json()["paths"]
    assert {
        "/api/profiles",
        "/api/profiles/{profile_id}",
        "/api/profiles/{profile_id}/apply",
        "/api/profiles/import",
        "/api/profiles/{profile_id}/export",
    } <= set(paths)
