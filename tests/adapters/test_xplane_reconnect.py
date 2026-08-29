"""An X-Plane restart mid-session reassigns every dataref/command id it hands out.

Confirmed against a live X-Plane 12: a stale numeric id answers
``/api/v2/datarefs/{id}/value`` with **HTTP 404** (``invalid_dataref_id``), never a
200 with a stale value — the design below leans on that. Before this file's
fix existed, that 404 propagated straight out of
:meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.stream_state`, closed
``/ws/state``, and every browser reconnect just re-hit the same never-refreshed
adapter singleton — the instructor's only recovery was restarting the backend
process by hand.

No socket is opened. A :class:`httpx.MockTransport` plays the Web API, the same
pattern as ``test_xplane_camera.py``, extended with a ``.../value`` handler and
a ``restart()`` that reassigns every id and 404s the old ones — a scripted
stand-in for what a live X-Plane restart actually does.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from adapters.xplane.xplane_adapter import (
    _MAX_RERESOLVE_ATTEMPTS,
    _RERESOLVE_DEBOUNCE_S,
    COMMANDS,
    DATAREFS,
    XPlaneNotReachable,
    XPlaneSimAdapter,
)
from core.models import AircraftState

_LOGGER_NAME = "adapters.xplane.xplane_adapter"


class _FakeWebApi:
    """A scripted X-Plane Web API whose ids can be reassigned mid-test.

    ``restart()`` is the whole point: it mints a fresh id for every dataref
    and command, and any old id becomes an ``invalid_dataref_id``/
    ``invalid_command_id`` 404 — exactly what the live probe on this branch
    observed.
    """

    def __init__(self, published_commands: Iterable[str]) -> None:
        self._published_commands = sorted(set(published_commands))
        self._generation = 0
        self._dataref_ids: dict[str, int] = {}
        self._command_ids: dict[str, int] = {}
        self._values: dict[int, float] = {}
        self.index_fetches = 0
        self.value_reads = 0
        self.unreachable = False
        self.values_always_404 = False
        self._assign_ids()

    def _assign_ids(self) -> None:
        self._generation += 1
        base = self._generation * 1_000_000
        self._dataref_ids = {path: base + i for i, path in enumerate(DATAREFS.values(), start=1)}
        self._command_ids = {
            path: base + 500_000 + i for i, path in enumerate(self._published_commands, start=1)
        }
        self._values = dict.fromkeys(self._dataref_ids.values(), 0.0)

    def restart(self) -> None:
        """Reassign every id, the way a live X-Plane restart does."""
        self._assign_ids()

    def id_for(self, dataref_key: str) -> int:
        return self._dataref_ids[DATAREFS[dataref_key]]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("connection refused", request=request)
        url = urlparse(str(request.url))
        if url.path == "/api/v2/datarefs":
            self.index_fetches += 1
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"name": path, "id": dataref_id}
                        for path, dataref_id in self._dataref_ids.items()
                    ]
                },
            )
        if url.path == "/api/v2/commands":
            wanted = parse_qs(url.query).get("filter[name]", [""])[0]
            command_id = self._command_ids.get(wanted)
            data = [] if command_id is None else [{"name": wanted, "id": command_id}]
            return httpx.Response(200, json={"data": data})
        if url.path.startswith("/api/v2/command/") and url.path.endswith("/activate"):
            command_id = int(url.path.split("/")[-2])
            if command_id not in self._command_ids.values():
                return httpx.Response(
                    404,
                    json={
                        "error_code": "invalid_command_id",
                        "error_message": f"Command id {command_id} doesn't exist",
                    },
                )
            return httpx.Response(200, json={"data": None})
        if url.path.startswith("/api/v2/datarefs/") and url.path.endswith("/value"):
            dataref_id = int(url.path.split("/")[-2])
            if request.method == "GET":
                self.value_reads += 1
            if self.values_always_404 or dataref_id not in self._values:
                return httpx.Response(
                    404,
                    json={
                        "error_code": "invalid_dataref_id",
                        "error_message": f"Dataref id {dataref_id} doesn't exist",
                    },
                )
            if request.method == "GET":
                return httpx.Response(200, json={"data": self._values[dataref_id]})
            if request.method == "PATCH":
                self._values[dataref_id] = json.loads(request.content)["data"]
                return httpx.Response(200, json={"data": None})
        return httpx.Response(404, json={"error": url.path})  # pragma: no cover - a test bug


def _script(monkeypatch: pytest.MonkeyPatch, published_commands: Iterable[str]) -> _FakeWebApi:
    """Make every :class:`httpx.AsyncClient` the adapter builds talk to a scripted install."""
    api = _FakeWebApi(published_commands)
    real_client = httpx.AsyncClient

    def build_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        del args
        return real_client(
            base_url=str(kwargs.get("base_url", "")),
            transport=httpx.MockTransport(api.handle),
        )

    monkeypatch.setattr(httpx, "AsyncClient", build_client)
    return api


async def _connected(monkeypatch: pytest.MonkeyPatch) -> tuple[XPlaneSimAdapter, _FakeWebApi]:
    """A connected adapter against an install publishing every required command."""
    api = _script(monkeypatch, COMMANDS.values())
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    return adapter, api


async def test_stream_state_self_heals_after_an_xplane_restart(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The reported bug: a restart mid-session must not hang telemetry forever."""
    adapter, api = await _connected(monkeypatch)
    stale_latitude_id = adapter._ids["latitude"]

    api.restart()

    stream = adapter.stream_state(0.0)
    try:
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            state = await asyncio.wait_for(anext(stream), timeout=5.0)
    finally:
        await stream.aclose()

    assert isinstance(state, AircraftState)
    assert adapter._ids["latitude"] != stale_latitude_id
    assert adapter._ids["latitude"] == api.id_for("latitude")
    assert "re-resolving" in caplog.text.lower()


async def test_stream_state_propagates_immediately_when_xplane_is_truly_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No point retrying reads when reconnecting itself cannot reach X-Plane."""
    adapter, api = await _connected(monkeypatch)
    api.unreachable = True

    stream = adapter.stream_state(0.0)
    try:
        with pytest.raises(XPlaneNotReachable):
            await asyncio.wait_for(anext(stream), timeout=5.0)
    finally:
        await stream.aclose()


async def test_stream_state_gives_up_after_max_reresolve_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconnecting succeeds but reads keep 404ing: bounded retries, not a spin.

    Distinct from the fully-unreachable case above: here every ``connect()``
    X-Plane's index/commands endpoints answer fine, so ``_reresolve()`` itself
    never raises — only the per-tick read keeps failing, which is the case
    ``_MAX_RERESOLVE_ATTEMPTS`` exists to bound.
    """
    adapter, api = await _connected(monkeypatch)
    api.values_always_404 = True

    stream = adapter.stream_state(0.0)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await asyncio.wait_for(anext(stream), timeout=5.0)
    finally:
        await stream.aclose()
    # One read per attempt, one retry per failure up to the cap: the loop must
    # not have spun past it.
    assert api.value_reads <= (_MAX_RERESOLVE_ATTEMPTS + 1) * len(DATAREFS)


async def test_reresolve_debounces_concurrent_callers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two callers hitting stale ids at once must not each tear down the connection.

    ``connect()`` itself costs more than one ``/api/v2/datarefs`` fetch (its
    own scan, plus :func:`~adapters.xplane.traffic_bridge.probe`'s separate
    one) — so rather than hard-code that count, this measures what one solo
    :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter._reresolve` costs
    and asserts a *pair* of concurrent ones costs exactly the same, not double.
    """
    adapter, api = await _connected(monkeypatch)

    fetches_before_solo = api.index_fetches
    await adapter._reresolve()
    solo_cost = api.index_fetches - fetches_before_solo
    assert solo_cost > 0

    # Past the debounce window, so the pair below is not short-circuited by
    # the solo reresolve just above — it needs to race each other, not this.
    adapter._last_resolved_at -= _RERESOLVE_DEBOUNCE_S
    fetches_before_pair = api.index_fetches

    await asyncio.gather(adapter._reresolve(), adapter._reresolve())

    assert api.index_fetches - fetches_before_pair == solo_cost


async def test_write_recovers_once_after_a_stale_id(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, api = await _connected(monkeypatch)
    api.restart()

    await adapter._write("indicated_airspeed", 91.0)

    fresh_id = api.id_for("indicated_airspeed")
    assert api._values[fresh_id] == 91.0


async def test_activate_recovers_once_after_a_stale_command_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, api = await _connected(monkeypatch)
    api.restart()
    key = next(iter(COMMANDS))

    await adapter._activate(key)  # must not raise

    assert adapter._command_ids[key] == api._command_ids[COMMANDS[key]]
