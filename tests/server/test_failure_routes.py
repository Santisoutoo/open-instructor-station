"""``/api/failures/*`` — inject, arm, clear; the watcher that evaluates triggers.

Two things here are worth more than the rest of the file.

**``active`` is always the simulator's own truth (D10).** Every assertion about
what is "failed" reads ``GET /api/failures/status``'s ``active`` list, which
comes straight from ``adapter.get_active_failures()`` — never from a
server-side ledger, because a teleport's ``fix_all_systems`` would repair
everything behind such a ledger's back.

**The watcher integration test is the one honest proof of the whole loop.**
``FakeSimAdapter`` really flies (§6.3): the trigger tests below arm a failure
against a fake in motion and poll ``/status`` until the scheduler's watcher —
a real ``asyncio.Task`` consuming ``adapter.stream_state()`` — moves it from
``armed`` to ``active``, with no simulator and no mocking of time.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.failures import FAILURE_CATALOGUE, FailureRef
from core.models import AircraftState
from core.sim_adapter import Capabilities
from server import failure_routes
from server.app import create_app
from server.deps import reset_adapter
from server.failure_routes import reset_failures

#: A short, level-flight state — used whenever the test only cares about a
#: failure_id, not about the aircraft actually moving.
LEVEL_STATE = AircraftState(
    latitude=40.0,
    longitude=-3.0,
    altitude_ft=3000.0,
    heading_deg=0.0,
    ias_kt=120.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=False,
)

#: Descends fast enough that a 100 ft trigger fires within a couple of
#: seconds — steep and unrealistic on purpose, this only exercises the
#: watcher's mechanism, not a plausible flight profile.
DESCENDING_STATE = LEVEL_STATE.model_copy(update={"vertical_speed_fpm": -6000.0})


class _NoFailuresAdapter(FakeSimAdapter):
    """A fake that declares every capability except ``can_inject_failures``."""

    @property
    def name(self) -> str:
        return "no-failures"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(can_set_position=True, can_set_aircraft_state=True)


class _FlakyInjectAdapter(FakeSimAdapter):
    """Fails the first ``inject_failure`` call, then behaves normally."""

    def __init__(self) -> None:
        super().__init__()
        self._attempts = 0

    async def inject_failure(self, failure: FailureRef) -> None:
        self._attempts += 1
        if self._attempts == 1:
            raise RuntimeError("simulator unreachable")
        await super().inject_failure(failure)


@pytest.fixture(autouse=True)
def _reset_failures_state() -> Iterator[None]:
    """The scheduler and its watcher are module state — reset around every test."""
    reset_failures()
    yield
    reset_failures()


@pytest.fixture
def client() -> TestClient:
    """A client whose adapter is the default ``FakeSimAdapter``. No navdata involved."""
    return TestClient(create_app())


@pytest.fixture
def no_failures_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _NoFailuresAdapter())
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


@pytest.fixture
def flaky_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _FlakyInjectAdapter())
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


@pytest.fixture
def descending_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A fake flying a steep descent, so an altitude_below trigger fires live."""
    monkeypatch.setattr(
        server.deps,
        "_build_adapter",
        lambda _settings: FakeSimAdapter(initial_state=DESCENDING_STATE),
    )
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


def _poll_status(client: TestClient, *, timeout_s: float = 8.0) -> Iterator[dict[str, Any]]:
    """Yield ``/status`` bodies roughly every 20 ms until ``timeout_s`` elapses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get("/api/failures/status")
        assert response.status_code == 200, response.text
        yield response.json()
        time.sleep(0.02)


# ---------------------------------------------------------------------------
# Catalogue and status
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_catalogue_merges_metadata_with_the_adapters_manifest(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/failures/catalogue")
        assert response.status_code == 200
        body = response.json()
        assert body["adapter"] == "fake"
        assert [entry["failure_id"] for entry in body["failures"]] == [
            spec.failure_id for spec in FAILURE_CATALOGUE
        ]
        assert all(entry["supported"] for entry in body["failures"])
        assert all(entry["reason"] is None for entry in body["failures"])

    def test_catalogue_and_status_answer_without_the_capability(
        self, no_failures_client: TestClient
    ) -> None:
        """The two GETs are never gated — reads degrade instead (§2.1)."""
        with no_failures_client:
            catalogue = no_failures_client.get("/api/failures/catalogue")
            status = no_failures_client.get("/api/failures/status")
        assert catalogue.status_code == 200
        assert all(not entry["supported"] for entry in catalogue.json()["failures"])
        assert all(entry["reason"] for entry in catalogue.json()["failures"])
        assert status.status_code == 200
        assert status.json() == {"active": [], "armed": []}


class TestStatus:
    def test_status_starts_empty(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/failures/status")
        assert response.status_code == 200
        assert response.json() == {"active": [], "armed": []}


# ---------------------------------------------------------------------------
# Inject / clear / clear-all
# ---------------------------------------------------------------------------


class TestInjectAndClear:
    def test_inject_is_reported_active(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/failures/inject", json={"failure_id": "airframe.smoke"})
            assert response.status_code == 200
            status = client.get("/api/failures/status").json()
        assert {"failure_id": "airframe.smoke", "engine_index": None} in status["active"]

    def test_repeated_inject_stays_one_entry(self, client: TestClient) -> None:
        with client:
            client.post("/api/failures/inject", json={"failure_id": "airframe.smoke"})
            client.post("/api/failures/inject", json={"failure_id": "airframe.smoke"})
            status = client.get("/api/failures/status").json()
        matches = [f for f in status["active"] if f["failure_id"] == "airframe.smoke"]
        assert len(matches) == 1

    def test_clear_repairs_it(self, client: TestClient) -> None:
        with client:
            client.post("/api/failures/inject", json={"failure_id": "airframe.smoke"})
            response = client.post("/api/failures/clear", json={"failure_id": "airframe.smoke"})
        assert response.status_code == 200
        assert response.json()["active"] == []

    def test_clear_all_empties_both_lists_and_stops_the_watcher(self, client: TestClient) -> None:
        with client:
            inject = client.post("/api/failures/inject", json={"failure_id": "airframe.smoke"})
            assert inject.status_code == 200
            arm = client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "instruments.pitot",
                    "trigger": {"type": "delay", "delay_s": 3600.0},
                },
            )
            assert arm.status_code == 200
            assert failure_routes._watcher_task is not None

            response = client.post("/api/failures/clear-all")
        assert response.status_code == 200
        body = response.json()
        assert body["active"] == []
        assert body["armed"] == []
        assert failure_routes._watcher_task is None

    def test_an_indexed_failure_carries_its_engine_index(self, client: TestClient) -> None:
        with client:
            client.post(
                "/api/failures/inject",
                json={"failure_id": "engine.failure", "engine_index": 2},
            )
            status = client.get("/api/failures/status").json()
        assert {"failure_id": "engine.failure", "engine_index": 2} in status["active"]
        assert {"failure_id": "engine.failure", "engine_index": 1} not in status["active"]


# ---------------------------------------------------------------------------
# Arm / disarm
# ---------------------------------------------------------------------------


class TestArmAndDisarm:
    def test_arm_returns_the_armed_failure(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "airframe.smoke",
                    "trigger": {"type": "delay", "delay_s": 3600.0},
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["failure_id"] == "airframe.smoke"
        assert body["trigger"] == {"type": "delay", "delay_s": 3600.0}
        assert body["armed_id"]
        assert body["last_error"] is None

    def test_status_lists_an_armed_failure(self, client: TestClient) -> None:
        with client:
            client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "airframe.smoke",
                    "trigger": {"type": "delay", "delay_s": 3600.0},
                },
            )
            status = client.get("/api/failures/status").json()
        assert len(status["armed"]) == 1
        assert status["armed"][0]["failure_id"] == "airframe.smoke"

    def test_arming_twice_arms_two_entries(self, client: TestClient) -> None:
        """Not idempotent (§2) — an instructor may genuinely want both."""
        with client:
            request = {
                "failure_id": "airframe.smoke",
                "trigger": {"type": "delay", "delay_s": 3600.0},
            }
            client.post("/api/failures/arm", json=request)
            client.post("/api/failures/arm", json=request)
            status = client.get("/api/failures/status").json()
        assert len(status["armed"]) == 2

    def test_disarm_removes_the_entry_before_it_fires(self, client: TestClient) -> None:
        with client:
            arm = client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "airframe.smoke",
                    "trigger": {"type": "delay", "delay_s": 3600.0},
                },
            )
            armed_id = arm.json()["armed_id"]
            response = client.delete(f"/api/failures/armed/{armed_id}")
        assert response.status_code == 200
        assert response.json()["armed"] == []

    def test_disarm_unknown_id_is_404_with_the_may_have_fired_sentence(
        self, client: TestClient
    ) -> None:
        with client:
            response = client.delete("/api/failures/armed/not-a-real-id")
        assert response.status_code == 404
        assert "already fired" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Capability gating (§2.1, D14)
# ---------------------------------------------------------------------------


class TestCapabilityGating:
    def test_inject_is_refused(self, no_failures_client: TestClient) -> None:
        with no_failures_client:
            response = no_failures_client.post(
                "/api/failures/inject", json={"failure_id": "airframe.smoke"}
            )
        assert response.status_code == 501
        detail = response.json()["detail"]
        assert "no-failures" in detail
        assert "can_inject_failures" in detail

    def test_arm_is_refused(self, no_failures_client: TestClient) -> None:
        with no_failures_client:
            response = no_failures_client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "airframe.smoke",
                    "trigger": {"type": "delay", "delay_s": 1.0},
                },
            )
        assert response.status_code == 501

    def test_clear_is_refused(self, no_failures_client: TestClient) -> None:
        with no_failures_client:
            response = no_failures_client.post(
                "/api/failures/clear", json={"failure_id": "airframe.smoke"}
            )
        assert response.status_code == 501

    def test_clear_all_is_refused(self, no_failures_client: TestClient) -> None:
        with no_failures_client:
            response = no_failures_client.post("/api/failures/clear-all")
        assert response.status_code == 501


# ---------------------------------------------------------------------------
# Validation — 422 (§2.2)
# ---------------------------------------------------------------------------


class TestValidation:
    def test_unknown_failure_id_is_refused(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/failures/inject", json={"failure_id": "not.a.real.id"})
        assert response.status_code == 422

    def test_indexed_entry_without_an_index_is_refused(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/failures/inject", json={"failure_id": "engine.failure"})
        assert response.status_code == 422

    def test_non_indexed_entry_with_an_index_is_refused(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/failures/inject",
                json={"failure_id": "instruments.pitot", "engine_index": 1},
            )
        assert response.status_code == 422

    def test_negative_delay_is_refused(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "airframe.smoke",
                    "trigger": {"type": "delay", "delay_s": -1.0},
                },
            )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# The watcher, live against a flying fake (§6.3, §8.3)
# ---------------------------------------------------------------------------


class TestWatcherIntegration:
    def test_an_armed_altitude_trigger_fires_from_live_telemetry(
        self, descending_client: TestClient
    ) -> None:
        with descending_client:
            arm = descending_client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "instruments.pitot",
                    "trigger": {"type": "altitude_below", "altitude_ft": 2900.0},
                },
            )
            assert arm.status_code == 200, arm.text
            armed_id = arm.json()["armed_id"]

            final_status = None
            for status in _poll_status(descending_client):
                final_status = status
                active_ids = {f["failure_id"] for f in status["active"]}
                if "instruments.pitot" in active_ids:
                    break

        assert final_status is not None
        assert "instruments.pitot" in {f["failure_id"] for f in final_status["active"]}
        assert armed_id not in {a["armed_id"] for a in final_status["armed"]}

    def test_a_failed_injection_retries_and_reports_last_error(
        self, flaky_client: TestClient
    ) -> None:
        """The fake flies level; an already-satisfied trigger fires on the very first frame."""
        with flaky_client:
            arm = flaky_client.post(
                "/api/failures/arm",
                json={
                    "failure_id": "instruments.pitot",
                    "trigger": {"type": "altitude_below", "altitude_ft": 3000.0},
                },
            )
            assert arm.status_code == 200, arm.text

            seen_last_error = False
            final_status = None
            for status in _poll_status(flaky_client):
                final_status = status
                if any(entry["last_error"] for entry in status["armed"]):
                    seen_last_error = True
                if "instruments.pitot" in {f["failure_id"] for f in status["active"]}:
                    break

        assert final_status is not None
        assert seen_last_error, "expected the failed first attempt to surface last_error"
        assert "instruments.pitot" in {f["failure_id"] for f in final_status["active"]}
        assert final_status["armed"] == []


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_openapi_exposes_the_failures_surface(client: TestClient) -> None:
    """``npm run generate:api`` reads this; the panel's types come from nowhere else."""
    with client:
        response = client.get("/openapi.json")
    paths = response.json()["paths"]
    assert {
        "/api/failures/catalogue",
        "/api/failures/status",
        "/api/failures/inject",
        "/api/failures/arm",
        "/api/failures/armed/{armed_id}",
        "/api/failures/clear",
        "/api/failures/clear-all",
    } <= set(paths)
