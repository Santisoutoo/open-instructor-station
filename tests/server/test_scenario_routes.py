"""``/api/scenarios/*`` — manifest, detail, run, poll (docs/designs/scenario-generator.md §3, §8.3).

Against ``TestClient`` + ``FakeSimAdapter``, exercising the real shipped
catalogue (``core/scenarios/data/``) and the ``ZZZZ`` fixture world from
``tests/server/conftest.py`` — ``bird-strike``/``go-around`` both resolve
against runway 36 there.

**``FakeSimAdapter`` declares every capability, including ``can_spawn_traffic``**
(it is the reference implementation — see ``adapters/fake/fake_adapter.py``),
so the live "greyed out with a reason" demonstration needs an adapter that
does NOT declare it, the same shape as ``test_failure_routes.py``'s
``_NoFailuresAdapter``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.failures import InjectFailureRequest
from core.models import AircraftSetup
from core.navdata.in_memory import InMemoryNavdataProvider
from core.placements import RunwayThresholdPlacementRequest
from core.scenarios.loader import LoadedScenario, ScenarioLoadError
from core.scenarios.models import ScenarioDocument, ScenarioFailuresBlock
from core.sim_adapter import Capabilities
from server import scenario_routes
from server.app import create_app
from server.deps import reset_adapter
from server.scenario_engine import reset_scenarios

# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class _NoTrafficAdapter(FakeSimAdapter):
    """Every capability except ``can_spawn_traffic`` — "every current adapter" (§8)."""

    @property
    def name(self) -> str:
        return "no-traffic"

    @property
    def capabilities(self) -> Capabilities:
        return super().capabilities.model_copy(update={"can_spawn_traffic": False})


class _SlowAdapter(FakeSimAdapter):
    """Adds a delay to ``apply_setup`` so a started run stays ``"running"`` long
    enough for the second-POST-while-in-progress assertion to be deterministic
    rather than a race against how fast the Fake completes a scenario."""

    async def apply_setup(self, setup: AircraftSetup) -> None:
        await asyncio.sleep(0.3)
        await super().apply_setup(setup)


# ---------------------------------------------------------------------------
# A scenario referencing an airport absent from the fixture world (D10, §8.3's
# degradation case) — built in-memory and injected via monkeypatch, since the
# shipped catalogue in core/scenarios/data/ is Track B's content, not this
# track's to add a bad-airport file to.
# ---------------------------------------------------------------------------

_DEGRADED_DOCUMENT = ScenarioDocument(
    name="Degraded",
    description=(
        "References an airport absent from the fixture navdata world; the "
        "failures block after it must stay pending when the position step fails."
    ),
    position=RunwayThresholdPlacementRequest(
        type="runway_threshold", airport_icao="ZZZQ", runway_ident="09"
    ),
    failures=ScenarioFailuresBlock(immediate=(InjectFailureRequest(failure_id="airframe.smoke"),)),
)
_DEGRADED_SCENARIO = LoadedScenario(
    id="degraded-scenario", document=_DEGRADED_DOCUMENT, source_path=Path("<test>")
)


def _only_degraded_scenario() -> tuple[tuple[LoadedScenario, ...], tuple[ScenarioLoadError, ...]]:
    return (_DEGRADED_SCENARIO,), ()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_scenarios_state() -> Iterator[None]:
    """The engine's run state is module state — reset around every test."""
    reset_scenarios()
    yield
    reset_scenarios()


@pytest.fixture
def no_traffic_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose adapter declares every capability except ``can_spawn_traffic``."""
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _NoTrafficAdapter())
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


@pytest.fixture
def slow_client(
    monkeypatch: pytest.MonkeyPatch, navdata: InMemoryNavdataProvider
) -> Iterator[TestClient]:
    del navdata  # ordering dependency only — the ZZZZ world for go-around/bird-strike
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _SlowAdapter())
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


@pytest.fixture
def degraded_client(
    monkeypatch: pytest.MonkeyPatch, navdata: InMemoryNavdataProvider
) -> Iterator[TestClient]:
    """A client whose catalogue is a single scenario naming an unknown airport."""
    del navdata  # ZZZZ exists in this world; ZZZQ deliberately does not
    monkeypatch.setattr(scenario_routes, "load_all_scenarios", _only_degraded_scenario)
    yield TestClient(create_app())


def _poll_run(client: TestClient, *, timeout_s: float = 8.0) -> Iterator[dict[str, Any] | None]:
    """Yield ``GET /scenarios/run`` bodies roughly every 20 ms until ``timeout_s`` elapses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get("/api/scenarios/run")
        assert response.status_code == 200, response.text
        yield response.json()
        time.sleep(0.02)


# ---------------------------------------------------------------------------
# Unknown scenario id
# ---------------------------------------------------------------------------


class TestUnknownScenario:
    def test_get_detail_is_404(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/scenarios/not-a-real-scenario")
        assert response.status_code == 404
        assert response.json()["detail"] == "Scenario 'not-a-real-scenario' is not defined."

    def test_post_run_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/scenarios/not-a-real-scenario/run")
        assert response.status_code == 404
        assert response.json()["detail"] == "Scenario 'not-a-real-scenario' is not defined."


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_lists_every_shipped_scenario(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/scenarios")
        assert response.status_code == 200
        body = response.json()
        assert body["adapter"] == "fake"
        assert body["load_errors"] == []
        ids = [row["id"] for row in body["scenarios"]]
        assert ids == sorted(ids)
        assert "engine-failure-after-v1" in ids
        assert "tcas-resolution-advisory" in ids

    def test_tcas_is_unavailable_without_can_spawn_traffic(
        self, no_traffic_client: TestClient
    ) -> None:
        with no_traffic_client:
            response = no_traffic_client.get("/api/scenarios")
        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()["scenarios"]}
        assert rows["tcas-resolution-advisory"]["available"] is False
        assert "can_spawn_traffic" in rows["tcas-resolution-advisory"]["reason"]
        # Every other shipped scenario needs no traffic capability.
        for scenario_id, row in rows.items():
            if scenario_id != "tcas-resolution-advisory":
                assert row["available"] is True, (scenario_id, row["reason"])


class TestDetail:
    def test_returns_the_full_document(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/scenarios/engine-failure-after-v1")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "engine-failure-after-v1"
        assert body["available"] is True
        assert body["document"]["position"]["airport_icao"] == "ZZZZ"


# ---------------------------------------------------------------------------
# Capability gating (D11, §3.2)
# ---------------------------------------------------------------------------


class TestCapabilityGating:
    def test_run_is_refused_with_501_naming_the_missing_flag(
        self, no_traffic_client: TestClient
    ) -> None:
        with no_traffic_client:
            response = no_traffic_client.post("/api/scenarios/tcas-resolution-advisory/run")
        assert response.status_code == 501
        detail = response.json()["detail"]
        assert "can_spawn_traffic" in detail
        assert "no-traffic" in detail
        assert "tcas-resolution-advisory" in detail

    def test_run_status_is_not_started_when_refused(self, no_traffic_client: TestClient) -> None:
        with no_traffic_client:
            no_traffic_client.post("/api/scenarios/tcas-resolution-advisory/run")
            status = no_traffic_client.get("/api/scenarios/run")
        assert status.status_code == 200
        assert status.json() is None


# ---------------------------------------------------------------------------
# Concurrency (D9)
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_a_second_run_while_one_is_in_progress_is_409(self, slow_client: TestClient) -> None:
        with slow_client:
            first = slow_client.post("/api/scenarios/go-around/run")
            assert first.status_code == 200, first.text
            assert first.json()["status"] == "running"

            second = slow_client.post("/api/scenarios/bird-strike/run")
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert "go-around" in detail
        assert "already running" in detail


# ---------------------------------------------------------------------------
# A normal run, end to end (§8.3's central assertion: the read-back)
# ---------------------------------------------------------------------------


class TestNormalRun:
    def test_bird_strike_reaches_completed_and_the_adapter_reflects_it(
        self, client: TestClient
    ) -> None:
        with client:
            start = client.post("/api/scenarios/bird-strike/run")
            assert start.status_code == 200, start.text
            assert start.json()["status"] == "running"
            assert {step["status"] for step in start.json()["steps"]} == {"pending"}

            final = None
            for body in _poll_run(client):
                if body is not None and body["status"] != "running":
                    final = body
                    break

            assert final is not None
            assert final["status"] == "completed", final
            assert final["finished_at"] is not None
            statuses = {step["name"]: step["status"] for step in final["steps"]}
            assert statuses == {
                "weather": "done",
                "aircraft_state": "done",
                "position": "done",
                "failures": "done",
            }

            # The read-back — not the absence of an exception (§8.3).
            weather = client.get("/api/weather").json()
            assert weather["visibility_m"] == pytest.approx(20_000.0)
            assert weather["cloud_layers"] == []

            state = client.get("/api/state").json()
            assert state["on_ground"] is False

            failures_status = client.get("/api/failures/status").json()
            assert {"failure_id": "airframe.bird_strike", "engine_index": None} in (
                failures_status["active"]
            )


# ---------------------------------------------------------------------------
# Degradation: a navdata-absent airport fails the run, not the pre-flight (D10)
# ---------------------------------------------------------------------------


class TestDegradedRun:
    def test_an_unresolvable_airport_fails_the_position_step_and_leaves_the_rest_pending(
        self, degraded_client: TestClient
    ) -> None:
        with degraded_client:
            start = degraded_client.post("/api/scenarios/degraded-scenario/run")
            assert start.status_code == 200, start.text

            final = None
            for body in _poll_run(degraded_client):
                if body is not None and body["status"] != "running":
                    final = body
                    break

        assert final is not None
        assert final["status"] == "failed"
        steps = {step["name"]: step for step in final["steps"]}
        assert steps["position"]["status"] == "failed"
        assert steps["position"]["error"]
        assert steps["aircraft_state"]["status"] == "failed"
        assert steps["failures"]["status"] == "pending"


# ---------------------------------------------------------------------------
# GET /run before anything has run
# ---------------------------------------------------------------------------


class TestNoRunYet:
    def test_returns_200_with_a_null_body(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/scenarios/run")
        assert response.status_code == 200
        assert response.json() is None


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_openapi_exposes_the_scenarios_surface(client: TestClient) -> None:
    """``npm run generate:api`` reads this; the panel's types come from nowhere else."""
    with client:
        response = client.get("/openapi.json")
    paths = response.json()["paths"]
    assert {
        "/api/scenarios",
        "/api/scenarios/run",
        "/api/scenarios/{scenario_id}",
        "/api/scenarios/{scenario_id}/run",
    } <= set(paths)
