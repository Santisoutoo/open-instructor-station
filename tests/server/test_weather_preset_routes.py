"""``/api/weather/presets/user/*`` — CRUD, ordering, and the "no capability gate" clause.

Against ``TestClient`` + ``FakeSimAdapter``, a ``tmp_path``-backed
``WeatherPresetStore`` (the same monkeypatch-the-builder pattern
``reset_navdata()``/``reset_adapter()`` already establish) and the ``ZZZZ``
fixture world from ``tests/server/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import core.weather.user_presets as user_presets_module
import server.deps
from adapters.fake import FakeSimAdapter
from core.navdata.in_memory import InMemoryNavdataProvider
from core.sim_adapter import Capabilities
from core.weather.user_presets import WeatherPresetStore
from server.app import create_app
from server.deps import reset_adapter, reset_weather_preset_store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _NoWeatherAdapter(FakeSimAdapter):
    """Every capability except ``can_set_weather`` — ``test_weather_routes.py``'s pattern."""

    @property
    def capabilities(self) -> Capabilities:
        return super().capabilities.model_copy(update={"can_set_weather": False})


@pytest.fixture
def preset_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[WeatherPresetStore]:
    store = WeatherPresetStore(tmp_path / "weather_presets")
    monkeypatch.setattr(server.deps, "_build_weather_preset_store", lambda _settings: store)
    reset_weather_preset_store()
    yield store
    reset_weather_preset_store()


@pytest.fixture
def client(
    navdata: InMemoryNavdataProvider, preset_store: WeatherPresetStore
) -> Iterator[TestClient]:
    del navdata, preset_store  # ordering dependency only
    yield TestClient(create_app())


@pytest.fixture
def no_weather_client(
    navdata: InMemoryNavdataProvider,
    preset_store: WeatherPresetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    del navdata, preset_store  # ordering dependency only
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _NoWeatherAdapter())
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


def _draft_body(name: str = "Low vis drill") -> dict[str, object]:
    return {
        "name": name,
        "description": "A test preset.",
        "setup": {"visibility_m": 550.0, "qnh_hpa": 996.0, "wind_layers": []},
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCrud:
    def test_full_round_trip(self, client: TestClient) -> None:
        with client:
            created = client.post("/api/weather/presets/user", json=_draft_body())
            assert created.status_code == 201, created.text
            preset_id = created.json()["preset_id"]

            listing = client.get("/api/weather/presets/user")
            assert preset_id in [row["preset_id"] for row in listing.json()]

            fetched = client.get(f"/api/weather/presets/user/{preset_id}")
            assert fetched.status_code == 200
            assert fetched.json()["name"] == "Low vis drill"

            deleted = client.delete(f"/api/weather/presets/user/{preset_id}")
            assert deleted.status_code == 204

            after_delete = client.get(f"/api/weather/presets/user/{preset_id}")
        assert after_delete.status_code == 404
        assert after_delete.json()["detail"] == f"No saved weather preset {preset_id!r}."

    def test_delete_of_unknown_id_names_may_already_be_deleted(self, client: TestClient) -> None:
        with client:
            response = client.delete("/api/weather/presets/user/" + "0" * 32)
        assert response.status_code == 404
        assert "may already be deleted" in response.json()["detail"]

    def test_create_with_a_nameless_body_is_422(self, client: TestClient) -> None:
        body = _draft_body()
        del body["name"]
        with client:
            response = client.post("/api/weather/presets/user", json=body)
        assert response.status_code == 422

    def test_create_with_an_extra_field_is_422(self, client: TestClient) -> None:
        body = _draft_body()
        body["colour"] = "blue"
        with client:
            response = client.post("/api/weather/presets/user", json=body)
        assert response.status_code == 422

    def test_list_is_newest_first(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instants = iter(
            [datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC), datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)]
        )
        monkeypatch.setattr(
            user_presets_module,
            "datetime",
            type("_FixedClock", (), {"now": staticmethod(lambda tz=None: next(instants))}),
        )
        with client:
            client.post("/api/weather/presets/user", json=_draft_body("First"))
            client.post("/api/weather/presets/user", json=_draft_body("Second"))
            listing = client.get("/api/weather/presets/user")
        assert [row["name"] for row in listing.json()] == ["Second", "First"]

    def test_put_is_405_there_is_no_replace_endpoint(self, client: TestClient) -> None:
        with client:
            response = client.put("/api/weather/presets/user/" + "0" * 32, json=_draft_body())
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# Capability-free (WS-4: pure app data, never gated on can_set_weather)
# ---------------------------------------------------------------------------


class TestCapabilityFree:
    def test_list_answers_200_without_can_set_weather(self, no_weather_client: TestClient) -> None:
        with no_weather_client:
            response = no_weather_client.get("/api/weather/presets/user")
        assert response.status_code == 200

    def test_create_answers_201_without_can_set_weather(
        self, no_weather_client: TestClient
    ) -> None:
        with no_weather_client:
            response = no_weather_client.post("/api/weather/presets/user", json=_draft_body())
        assert response.status_code == 201

    def test_get_and_delete_answer_without_can_set_weather(
        self, no_weather_client: TestClient
    ) -> None:
        with no_weather_client:
            created = no_weather_client.post("/api/weather/presets/user", json=_draft_body())
            preset_id = created.json()["preset_id"]

            fetched = no_weather_client.get(f"/api/weather/presets/user/{preset_id}")
            assert fetched.status_code == 200

            deleted = no_weather_client.delete(f"/api/weather/presets/user/{preset_id}")
            assert deleted.status_code == 204


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_openapi_exposes_the_user_presets_surface(client: TestClient) -> None:
    """``npm run generate:api`` reads this; the panel's types come from nowhere else."""
    with client:
        response = client.get("/openapi.json")
    paths = response.json()["paths"]
    assert {
        "/api/weather/presets/user",
        "/api/weather/presets/user/{preset_id}",
    } <= set(paths)
    assert "201" in paths["/api/weather/presets/user"]["post"]["responses"]
