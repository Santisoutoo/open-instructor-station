"""The X-Plane camera mapping and its connect-time probe, pinned in CI.

``adapters/xplane/camera_commands.py`` ships **unverified guesses** — no camera
spike has been run (camera-manager.md §5.1) — and ``can_control_camera`` is
``True`` regardless (§5.2). What makes that safe is not the guesses being right;
it is the probe: every candidate command is looked up against the install's own
command index at :meth:`connect` time, and a view whose command is absent ships
``supported=False`` with a stated reason instead of an enabled button that
throws at runtime. A live run can only ever check that mechanism against *one*
build; this file checks it against every build a test cares to describe.

No socket is opened. A :class:`httpx.MockTransport` plays the Web API, so
``connect()``'s real code — the dataref scan, the required-versus-optional
command split, the id bookkeeping — runs unmodified against a scripted install.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from adapters.xplane.camera_commands import (
    CAMERA_COMMAND_PATHS,
    CAMERA_COMMANDS,
    command_key_for,
)
from adapters.xplane.xplane_adapter import (
    COMMANDS,
    DATAREFS,
    OPTIONAL_COMMANDS,
    XPlaneNotReachable,
    XPlaneSimAdapter,
)
from core.camera.models import CAMERA_VIEW_IDS, CameraOffset, CameraViewId
from core.sim_adapter import CapabilityNotSupported

#: camera-manager.md §5.2's own sentence, quoted here so a paraphrase in the
#: adapter fails this test rather than quietly diverging from the design.
CUSTOM_POSITIONS_REASON = (
    "Free-camera positioning needs the optional in-sim bridge on this X-Plane build."
)

#: An install with nothing missing: every required command and every camera
#: candidate. The baseline the degraded cases are described against.
FULLY_EQUIPPED = (*COMMANDS.values(), *OPTIONAL_COMMANDS.values())


def _candidate(view_id: CameraViewId) -> str:
    """The candidate command path for one view, for a test that needs a name.

    Narrows away the ``None`` that :class:`CameraCommandMapping` allows for a
    row the design gives no candidate at all — every row has one today, and a
    test asking for a name it does not have should say so loudly.
    """
    command = CAMERA_COMMANDS[view_id].command
    assert command is not None, f"{view_id!r} has no candidate command to probe"
    return command


class _FakeWebApi:
    """A scripted X-Plane Web API: an index of datarefs and a set of commands.

    ``published_commands`` is the whole point — it is how "this build does not
    have that command" is expressed. Ids are assigned in first-seen order so a
    test can assert *which* command was activated, not merely that one was.
    """

    def __init__(self, published_commands: Iterable[str]) -> None:
        self._dataref_ids = {path: index for index, path in enumerate(DATAREFS.values(), start=1)}
        self._command_ids = {
            path: index for index, path in enumerate(sorted(published_commands), start=1000)
        }
        self.activated: list[int] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        if url.path == "/api/v2/datarefs":
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
            if command_id is None:
                # The real Web API answers a name it does not publish with a
                # bare 404, not `200 {"data": []}` — confirmed live with the
                # Zibo 737 loaded (issue #217). The dataref sibling of this
                # lookup documents the same shape:
                # docs/research/zibo-737-autopilot-dataref-mapping.md §7.
                return httpx.Response(
                    404,
                    json={
                        "error_code": "invalid_command_name",
                        "error_message": f"Command '{wanted}' doesn't exist",
                    },
                )
            return httpx.Response(200, json={"data": [{"name": wanted, "id": command_id}]})
        if url.path.startswith("/api/v2/command/") and url.path.endswith("/activate"):
            self.activated.append(int(url.path.split("/")[-2]))
            return httpx.Response(200, json={"data": None})
        return httpx.Response(404, json={"error": url.path})  # pragma: no cover - a test bug

    def activated_paths(self) -> list[str]:
        """The command *paths* fired, in order — the ids are an implementation detail."""
        by_id = {command_id: path for path, command_id in self._command_ids.items()}
        return [by_id[command_id] for command_id in self.activated]


def _script(monkeypatch: pytest.MonkeyPatch, published_commands: Iterable[str]) -> _FakeWebApi:
    """Make every :class:`httpx.AsyncClient` the adapter builds talk to a scripted install."""
    api = _FakeWebApi(published_commands)
    # Bound before the patch: the factory below must build a *real* client, and
    # looking the class up by name inside it would find the patch itself.
    real_client = httpx.AsyncClient

    def build_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        del args
        return real_client(
            base_url=str(kwargs.get("base_url", "")),
            transport=httpx.MockTransport(api.handle),
        )

    # Patched on the ``httpx`` module itself, which is the very object
    # ``adapters.xplane.xplane_adapter`` reaches through when it builds a client.
    monkeypatch.setattr(httpx, "AsyncClient", build_client)
    return api


async def _connected(
    monkeypatch: pytest.MonkeyPatch, published_commands: Iterable[str]
) -> tuple[XPlaneSimAdapter, _FakeWebApi]:
    """A connected adapter against an install publishing exactly ``published_commands``."""
    api = _script(monkeypatch, published_commands)
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    return adapter, api


# --------------------------------------------------------------------------
# The mapping module
# --------------------------------------------------------------------------


def test_every_catalogue_view_has_a_row() -> None:
    """The drift guard, asserted rather than left to an import-time ``assert``.

    ``failure_datarefs.py``'s lesson: a catalogue id with no row here is a view
    the manifest cannot answer for, and a row with no catalogue id is a command
    nothing can ever fire.
    """
    assert tuple(CAMERA_COMMANDS) == CAMERA_VIEW_IDS


def test_no_command_name_is_claimed_as_high_confidence() -> None:
    """§5.1 marks every row "verify in spike" — none of them is fact yet.

    The honesty convention, made mechanical: the day a spike confirms a name,
    upgrading its confidence should be a deliberate edit that also changes this
    test, not something a distracted refactor can slip in.
    """
    assert {mapping.confidence for mapping in CAMERA_COMMANDS.values()} <= {"medium", "low"}
    assert CAMERA_COMMANDS["wing"].confidence == "low", (
        "§5.1's wing row names no command at all, only 'a spot/external side view'"
    )


def test_candidate_paths_are_distinct_x_plane_view_commands() -> None:
    """Two views sharing one command would make the manifest lie by duplication."""
    paths = [mapping.command for mapping in CAMERA_COMMANDS.values() if mapping.command]
    assert len(set(paths)) == len(paths)
    assert all(path.startswith("sim/view/") for path in paths)


def test_probe_keys_cover_exactly_the_rows_with_a_candidate() -> None:
    """A row with no candidate has nothing to probe; one with a candidate must be probed."""
    expected = {
        command_key_for(view_id)
        for view_id, mapping in CAMERA_COMMANDS.items()
        if mapping.command is not None
    }
    assert set(CAMERA_COMMAND_PATHS) == expected
    assert dict(OPTIONAL_COMMANDS) == dict(CAMERA_COMMAND_PATHS)


def test_probe_keys_cannot_collide_with_the_required_commands() -> None:
    """Both namespaces share one ``_command_ids`` dict; a collision would misfire a view."""
    assert set(CAMERA_COMMAND_PATHS).isdisjoint(COMMANDS)


# --------------------------------------------------------------------------
# The connect-time probe
# --------------------------------------------------------------------------


async def test_a_build_publishing_every_candidate_supports_every_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _ = await _connected(monkeypatch, FULLY_EQUIPPED)
    try:
        manifest = await adapter.get_camera_support()
        assert tuple(entry.view_id for entry in manifest.views) == CAMERA_VIEW_IDS
        assert all(entry.supported for entry in manifest.views)
        assert all(entry.reason is None for entry in manifest.views)
        assert manifest.caveat, (
            "a probe proves a command name exists, not that it selects the intended "
            "camera; the manifest must say so out loud"
        )
    finally:
        await adapter.disconnect()


async def test_a_build_publishing_no_camera_command_still_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the optional tier: a wrong guess costs buttons, not the connection.

    Every view ships unsupported *with the candidate name in the reason*, so
    the instructor — and whoever runs the spike next — can see which name was
    tried instead of a bare "unavailable".

    Regression for issue #217: ``_FakeWebApi`` answers every missing command
    here with a real **404**, the same status the live Web API gave with the
    Zibo 737 loaded — not the ``200 {"data": []}`` the fake used to fabricate,
    which let ``_lookup_command_id``'s ``raise_for_status()`` bug through this
    exact test unnoticed. ``connect()`` reaching this point at all is the
    proof that the 404 is handled, not just the empty-list case.
    """
    adapter, _ = await _connected(monkeypatch, COMMANDS.values())
    try:
        assert adapter.is_connected
        manifest = await adapter.get_camera_support()
        assert not any(entry.supported for entry in manifest.views)
        for entry in manifest.views:
            candidate = CAMERA_COMMANDS[entry.view_id].command
            assert candidate is not None
            assert entry.reason is not None and candidate in entry.reason
    finally:
        await adapter.disconnect()


async def test_a_partially_publishing_build_degrades_view_by_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Support is per view (D3), not all-or-nothing."""
    adapter, _ = await _connected(
        monkeypatch,
        [*COMMANDS.values(), _candidate("chase"), _candidate("tower")],
    )
    try:
        manifest = await adapter.get_camera_support()
        supported = {entry.view_id for entry in manifest.views if entry.supported}
        assert supported == {"chase", "tower"}
    finally:
        await adapter.disconnect()


async def test_lookup_command_id_returns_none_on_a_404() -> None:
    """Regression for issue #217.

    ``raise_for_status()`` used to run before the empty-``data`` check, so a
    404 — the real Web API's answer to a command name it does not publish —
    escaped as an unhandled ``httpx.HTTPStatusError`` instead of the
    documented ``None``. This has been locally fixed and lost at least twice
    before (per the issue), so this test proves the 404 path directly against
    its own handler — deliberately *not* :class:`_FakeWebApi`, so that a
    future revert of the fake back to ``200 {"data": []}`` (the exact drift
    that hid this bug from CI) cannot make this test pass vacuously.
    """

    def miss(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            404,
            json={
                "error_code": "invalid_command_name",
                "error_message": "Command doesn't exist",
            },
        )

    async with httpx.AsyncClient(
        base_url="http://x", transport=httpx.MockTransport(miss)
    ) as client:
        result = await XPlaneSimAdapter._lookup_command_id(client, "sim/view/does_not_exist")
    assert result is None


async def test_lookup_command_id_still_raises_on_a_server_error() -> None:
    """The fix narrows to 404 specifically — a real failure must still propagate."""

    def blow_up(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, json={"error_code": "internal", "error_message": "boom"})

    async with httpx.AsyncClient(
        base_url="http://x", transport=httpx.MockTransport(blow_up)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await XPlaneSimAdapter._lookup_command_id(client, "sim/view/chase")


async def test_a_missing_required_command_still_fails_the_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optional tier must not have softened the load-bearing one.

    ``fix_all_systems`` is step 5 of every reposition; an install without it is
    one this adapter cannot honestly drive, and that stays fatal.
    """
    _script(
        monkeypatch,
        [path for path in FULLY_EQUIPPED if path != COMMANDS["fix_all_systems"]],
    )
    adapter = XPlaneSimAdapter()
    with pytest.raises(XPlaneNotReachable, match="fix_all_systems"):
        await adapter.connect()
    assert adapter.is_connected is False


# --------------------------------------------------------------------------
# Selecting a view
# --------------------------------------------------------------------------


async def test_set_camera_view_fires_the_mapped_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, api = await _connected(monkeypatch, FULLY_EQUIPPED)
    try:
        for view_id in CAMERA_VIEW_IDS:
            await adapter.set_camera_view(view_id)
        assert api.activated_paths() == [_candidate(view_id) for view_id in CAMERA_VIEW_IDS]
    finally:
        await adapter.disconnect()


async def test_set_camera_view_refuses_a_view_the_manifest_calls_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth, the ``_resolved_failure_dataref_ids`` posture.

    The UI gates on the manifest, so this should be unreachable — but an
    unsupported view firing *some other* view's command, or a ``KeyError``
    escaping as a 500, are both worse than a clean capability refusal.
    """
    adapter, api = await _connected(monkeypatch, [*COMMANDS.values(), _candidate("chase")])
    try:
        with pytest.raises(CapabilityNotSupported, match="can_control_camera"):
            await adapter.set_camera_view("tower")
        assert api.activated_paths() == []
        await adapter.set_camera_view("chase")
        assert api.activated_paths() == [_candidate("chase")]
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# Custom offsets stay refused (§5.2 / D7)
# --------------------------------------------------------------------------


async def test_custom_positions_are_refused_with_the_designs_own_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Named views working must not drag free positioning along with them.

    ``XPLMCameraControl`` is plugin-only and §5.2's spike has not been run, so
    the honest answer is a refusal plus the design's stated reason — not an
    invented dataref mapping.
    """
    adapter, _ = await _connected(monkeypatch, FULLY_EQUIPPED)
    try:
        manifest = await adapter.get_camera_support()
        assert all(entry.supported for entry in manifest.views)
        assert manifest.custom_positions_supported is False
        assert manifest.custom_positions_reason == CUSTOM_POSITIONS_REASON

        assert await adapter.get_camera_offset() is None
        with pytest.raises(CapabilityNotSupported, match="can_control_camera"):
            await adapter.set_camera_offset(
                CameraOffset(
                    forward_m=10.0, right_m=0.0, up_m=5.0, look_offset_deg=0.0, pitch_deg=0.0
                )
            )
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# Before any connection
# --------------------------------------------------------------------------


async def test_the_manifest_answers_before_connecting_and_says_why() -> None:
    """A capability-free read (D2): "no" is an answer, never an exception.

    The reason must not be the "this build does not publish it" one — nothing
    has been probed yet, and blaming the install for the adapter never having
    connected would send someone hunting through X-Plane's command list for a
    problem that is on this side of the wire.
    """
    adapter = XPlaneSimAdapter()
    manifest = await adapter.get_camera_support()

    assert tuple(entry.view_id for entry in manifest.views) == CAMERA_VIEW_IDS
    for entry in manifest.views:
        assert entry.supported is False
        assert entry.reason is not None and "not connected" in entry.reason.lower()
    assert manifest.custom_positions_supported is False
    assert manifest.custom_positions_reason
    assert await adapter.get_camera_offset() is None


async def test_set_camera_view_refuses_while_disconnected() -> None:
    """``can_control_camera`` is ``True``, but nothing has resolved yet.

    ``_command_ids`` is empty until :meth:`connect` fills it, so every view
    looks exactly like one this build does not publish — the same degradation
    the failure mapping already documents. No socket is touched.
    """
    adapter = XPlaneSimAdapter()
    for view_id in CAMERA_VIEW_IDS:
        with pytest.raises(CapabilityNotSupported, match="can_control_camera"):
            await adapter.set_camera_view(view_id)


def test_the_fake_web_api_answers_the_filter_the_adapter_actually_sends() -> None:
    """Guard the stub itself.

    A query parameter the adapter no longer sends would make every probe above
    resolve nothing and the "degrades honestly" tests pass for the wrong reason.
    """
    api = _FakeWebApi(["sim/view/chase"])
    request = httpx.Request("GET", "http://x/api/v2/commands?filter%5Bname%5D=sim/view/chase")
    body = json.loads(api.handle(request).content)
    assert [entry["name"] for entry in body["data"]] == ["sim/view/chase"]


def test_the_fake_web_api_answers_a_command_miss_with_a_404() -> None:
    """Pins the fake's shape for a name it does not publish (issue #217).

    The real Web API's answer to an unrecognised ``filter[name]`` is a bare
    404, not ``200 {"data": []}`` — this is the exact behaviour the fake used
    to get wrong, which is how ``_lookup_command_id``'s ``raise_for_status()``
    bug survived every camera test in this file. If a future edit reverts the
    fake to a 200, this is the test that must catch it.
    """
    api = _FakeWebApi(["sim/view/chase"])
    request = httpx.Request(
        "GET", "http://x/api/v2/commands?filter%5Bname%5D=sim/view/does_not_exist"
    )
    response = api.handle(request)
    assert response.status_code == 404
