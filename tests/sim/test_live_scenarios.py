"""Every shipped, currently-available scenario, run end to end against a live
X-Plane. Never runs in CI.

Per ``docs/designs/scenario-generator.md`` §8.4: this is deliberately heavy —
13 sequential placements, some with weather writes that settle over tens of
seconds — and is the ``sim-validator`` agent's job, never a merge gate.

Run with a simulator loaded and its Web API enabled::

    pytest -m sim -k test_live_scenarios

Against ``TestClient`` + the real ``XPlaneSimAdapter``, with the ``ZZZZ``
fixture world (``tests/server/conftest.py::build_provider``) served as
navdata — every shipped scenario references ``ZZZZ``, never a real airport,
so this is the same fixture the Fake-backed contract tests already use, just
with a live adapter behind it.

**Everything goes through the REST API, never the adapter directly.**
``TestClient`` runs the ASGI app on its own internal event loop (a background
thread), separate from whichever loop a test coroutine runs under; the first
version of this test called ``adapter.get_aircraft_state()`` straight from an
``async def`` test body and hit ``RuntimeError: ... is bound to a different
event loop`` the moment two different loops touched the same
``httpx.AsyncClient``. Every other ``TestClient``-based test in this codebase
sidesteps this by staying synchronous and only ever calling through
``client.get``/``client.post`` — this file does the same, restoring position
via ``POST /api/position/apply`` and clearing failures via
``POST /api/failures/clear-all`` rather than reaching for the adapter.

Restores the aircraft to wherever it was before this file's one test, between
every scenario and again in a ``finally`` — a scenario run's own in-progress
state (an armed failure, a moved aircraft) must not leak into the next
scenario in the loop.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.xplane import XPlaneSimAdapter
from server.app import create_app
from server.deps import reset_adapter, reset_navdata
from server.scenario_engine import reset_scenarios
from tests.server.conftest import build_provider

pytestmark = pytest.mark.sim

#: How long one scenario run may take before this test gives up on it.
#: Generous: a weather-bearing scenario's cloud settle alone can take up to
#: 70s (adapters/xplane/xplane_adapter.py::_CLOUD_SETTLE_TIMEOUT_S), and the
#: run is otherwise sequential -- position, then weather, then failures.
_RUN_TIMEOUT_S = 120.0
_POLL_INTERVAL_S = 1.0


@pytest.fixture
def live_scenario_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A real ``XPlaneSimAdapter`` behind the shared fixture navdata world."""
    provider = build_provider()
    monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: XPlaneSimAdapter())
    reset_adapter()
    reset_navdata()
    reset_scenarios()
    with TestClient(create_app()) as client:
        yield client
    reset_scenarios()
    reset_adapter()
    reset_navdata()


def _poll_until_settled(client: TestClient) -> dict[str, Any]:
    """Poll ``GET /api/scenarios/run`` until the status leaves ``"running"``."""
    deadline = time.monotonic() + _RUN_TIMEOUT_S
    body: dict[str, Any] | None = None
    poll_count = 0
    while time.monotonic() < deadline:
        response = client.get("/api/scenarios/run")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body is not None
        if body["status"] != "running":
            return body
        poll_count += 1
        if poll_count % 10 == 0:
            print(
                f"[live-scenarios]   ... still running, step={body.get('steps')}",
                file=sys.stderr,
                flush=True,
            )
        time.sleep(_POLL_INTERVAL_S)
    raise AssertionError(f"scenario did not settle within {_RUN_TIMEOUT_S:.0f}s: {body}")


def _restore(client: TestClient, home: dict[str, Any]) -> None:
    """Clear every failure and put the aircraft back where this test found it.

    ``home``'s own ``ias_kt`` only applies if it was airborne -- a stationary
    placement on the ground always commands 0, matching
    ``tests/conftest.py``'s own restore branch (the "a placement now commands
    its own speed" fix this repo's ``CLAUDE.md`` documents: a parked
    aircraft handed a nonzero speed is fine, but an airborne one handed 0
    falls out of the sky below stall speed -- and the reverse, a parked one
    kept at cruise IAS, is just as wrong).
    """
    print("[live-scenarios]   restore: clearing failures", file=sys.stderr, flush=True)
    clear_response = client.post("/api/failures/clear-all")
    assert clear_response.status_code == 200, clear_response.text
    print("[live-scenarios]   restore: repositioning to home", file=sys.stderr, flush=True)
    restore_response = client.post(
        "/api/position/apply",
        json={
            "placement": {
                "type": "coordinate",
                "position": {
                    "latitude": home["latitude"],
                    "longitude": home["longitude"],
                    "altitude_ft": home["altitude_ft"],
                },
                "heading_deg": home["heading_deg"],
                "ias_kt": 0.0 if home["on_ground"] else home["ias_kt"],
            }
        },
    )
    assert restore_response.status_code == 200, restore_response.text
    print("[live-scenarios]   restore: done", file=sys.stderr, flush=True)


def test_every_available_scenario_runs_to_completion(live_scenario_client: TestClient) -> None:
    """Roadmap Phase 2 exit criterion 1's live half: every shipped scenario
    the active adapter can attempt reaches ``"completed"``, not ``"failed"``.

    Iterates the real shipped catalogue (``core/scenarios/data/``), skipping
    only the scenarios the manifest itself reports unavailable —
    ``tcas-resolution-advisory`` needs ``can_spawn_traffic``, which does not
    exist until Phase 3, and is the only one expected on this adapter.
    """
    client = live_scenario_client
    home = client.get("/api/state").json()

    manifest_response = client.get("/api/scenarios")
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()
    assert manifest["load_errors"] == [], (
        f"the shipped catalogue itself failed to load: {manifest['load_errors']}"
    )

    results: dict[str, str] = {}
    skipped: dict[str, str] = {}
    try:
        for scenario in sorted(manifest["scenarios"], key=lambda row: row["id"]):
            if not scenario["available"]:
                skipped[scenario["id"]] = scenario["reason"]
                continue

            start = time.monotonic()
            print(f"\n[live-scenarios] starting {scenario['id']}", file=sys.stderr, flush=True)
            response = client.post(f"/api/scenarios/{scenario['id']}/run")
            assert response.status_code == 200, (
                f"{scenario['id']}: POST /run returned {response.status_code}: {response.text}"
            )

            final = _poll_until_settled(client)
            results[scenario["id"]] = final["status"]
            elapsed = time.monotonic() - start
            print(
                f"[live-scenarios] {scenario['id']} -> {final['status']} in {elapsed:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            assert final["status"] == "completed", f"{scenario['id']} did not complete: {final}"

            # Restore between scenarios so the next one starts from a known
            # position and no armed/injected failure from this one leaks in.
            _restore(client, home)
    finally:
        _restore(client, home)

    # The exit-criterion assertion itself: every attempted scenario -- every
    # one the manifest itself declared available -- reached "completed".
    assert set(skipped) == {"tcas-resolution-advisory"}, (
        f"expected only tcas-resolution-advisory to be unavailable, got: {skipped}"
    )
    assert len(results) == 13, f"expected 13 attempted scenarios, ran {len(results)}: {results}"
    assert all(status == "completed" for status in results.values()), results
