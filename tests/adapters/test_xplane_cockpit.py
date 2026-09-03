"""The X-Plane cockpit control catalog runtime, pinned in CI (§8.4).

Mirrors ``test_xplane_camera.py``'s shape: no socket is opened, an
:class:`httpx.MockTransport` plays the Web API, and ``connect()``'s real code
runs unmodified against a scripted install. What this file adds is the
cockpit-specific machinery ``adapters/xplane/cockpit_controls.py`` owns —
live detection by dataref probe (D5), lazy per-name binding resolution with
its cache (D6), the aircraft-change hook (D7) and the five per-kind executors
(D2, §5.5) — exercised against the same ``fake-trainer`` catalog the
foundation's ``FakeSimAdapter`` and ``tests/core/fixtures/cockpit/fake-trainer``
already pin, so this file is not inventing a second oracle for what that
catalog contains.

The one correction from the camera mock this file repeats deliberately
(issue #217): a ``filter[name]`` miss on ``/api/v2/datarefs`` — used for both
the detection probe and binding resolution — answers a real **404**, not
``200 {"data": []}``.
"""

from __future__ import annotations

import base64
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from adapters.xplane import cockpit_controls
from adapters.xplane.xplane_adapter import (
    COMMANDS,
    DATAREFS,
    OPTIONAL_COMMANDS,
    OPTIONAL_DATAREFS,
    XPlaneSimAdapter,
)
from core.cockpit.catalog import load_all_catalogs
from core.cockpit.errors import (
    CockpitCatalogInactive,
    CockpitPreconditionUnmet,
    CockpitWriteRejected,
)
from core.cockpit.models import CockpitActuation
from core.models import AircraftSetup

#: The foundation's own YAML mirror of ``FakeSimAdapter``'s synthetic catalog
#: (docs/designs/cockpit-control-catalog.md D12, §8.1) — the oracle this file
#: reuses rather than inventing a second one. Bindings are ``fake/...``
#: strings; nothing here is a real X-Plane dataref.
_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "core" / "fixtures" / "cockpit"


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    """A catalog root holding only ``fake-trainer`` — the other fixture
    directories under ``tests/core/fixtures/cockpit/`` are deliberately
    broken (they exist to pin the LOADER's errors), and pulling them in here
    would make this file's request counts depend on a directory it does not
    own.
    """
    root = tmp_path / "cockpit_catalogs"
    shutil.copytree(_FIXTURE_ROOT / "fake-trainer", root / "fake-trainer")
    return root


class _FakeWebApi:
    """Scripts the parts of the Web API the cockpit runtime touches.

    Two disjoint namespaces share one growing id space:

    * **CORE** — this adapter's own :data:`DATAREFS`/:data:`OPTIONAL_DATAREFS`/
      :data:`COMMANDS`/:data:`OPTIONAL_COMMANDS`. Resolved by ``connect()``'s
      bulk, unfiltered ``/api/v2/datarefs`` scan and by per-name command
      lookups — always fully present here, matching an equipped install.
    * **CATALOG** — cockpit binding names (``fake/...``), resolved ONLY by a
      per-name ``filter[name]`` probe and deliberately absent from the
      unfiltered ``/api/v2/datarefs`` response: a cockpit runtime that read
      the full index instead of probing per name would find nothing here.
    """

    def __init__(self, *, acf_relative_path: str | None = "Aircraft/Fake/fake.acf") -> None:
        self._next_id = 1
        self._id_history: dict[int, str] = {}

        self._dataref_paths: dict[str, int] = {}
        self._dataref_values: dict[int, Any] = {}
        self._core_dataref_names: set[str] = set()
        self._command_paths: dict[str, int] = {}
        self._core_command_names: set[str] = set()

        self._retired_ids: set[int] = set()
        self._unavailable: set[str] = set()
        self._stuck: dict[int, Any] = {}
        self._toggle_links: dict[str, str] = {}
        self._encoder_links: dict[str, tuple[str, float]] = {}

        self.activated: list[int] = []
        self.writes: list[tuple[int, Any, int | None]] = []
        self.probed_names: list[str] = []
        self.full_index_requests = 0

        for path in DATAREFS.values():
            self._add_dataref(path, 0)
            self._core_dataref_names.add(path)
        for key, path in OPTIONAL_DATAREFS.items():
            if key == "acf_relative_path":
                continue
            self._add_dataref(path, 0)
            self._core_dataref_names.add(path)
        self._acf_relative_path_id: int | None = None
        self.set_acf_relative_path(acf_relative_path)

        for path in {*COMMANDS.values(), *OPTIONAL_COMMANDS.values()}:
            self._add_command(path)
            self._core_command_names.add(path)

    # -- setup ---------------------------------------------------------------

    def _add_dataref(self, path: str, value: Any) -> int:
        dataref_id = self._next_id
        self._next_id += 1
        self._dataref_paths[path] = dataref_id
        self._dataref_values[dataref_id] = value
        self._id_history[dataref_id] = path
        return dataref_id

    def _add_command(self, path: str) -> int:
        command_id = self._next_id
        self._next_id += 1
        self._command_paths[path] = command_id
        self._id_history[command_id] = path
        return command_id

    def set_acf_relative_path(self, path: str | None) -> None:
        """(Re)publish ``acf_relative_path``, or make it unavailable (``None``).

        The real dataref's numeric id is stable for the life of a connection
        — the adapter resolves it once, in ``connect()``'s own scan, and
        caches it in ``self._ids``. A changed VALUE under the SAME id is
        exactly how a real aircraft swap looks, so a call with an id already
        issued updates the value in place rather than reissuing a new id
        (that scenario is :meth:`retire_dataref`'s, not this one).
        """
        acf_path = OPTIONAL_DATAREFS["acf_relative_path"]
        if path is None:
            if self._acf_relative_path_id is not None:
                del self._dataref_paths[acf_path]
                del self._dataref_values[self._acf_relative_path_id]
                self._core_dataref_names.discard(acf_path)
                self._acf_relative_path_id = None
            return
        encoded = base64.b64encode(path.encode("ascii")).decode("ascii")
        if self._acf_relative_path_id is not None:
            self._dataref_values[self._acf_relative_path_id] = encoded
            return
        self._acf_relative_path_id = self._add_dataref(acf_path, encoded)
        self._core_dataref_names.add(acf_path)

    def publish_dataref(self, path: str, value: Any) -> int:
        self._unavailable.discard(path)
        return self._add_dataref(path, value)

    def publish_command(self, path: str) -> int:
        self._unavailable.discard(path)
        return self._add_command(path)

    def unpublish(self, path: str) -> None:
        """The NEXT ``filter[name]`` probe for ``path`` answers 404."""
        self._unavailable.add(path)

    def retire_dataref(self, path: str) -> None:
        """Simulate a plugin reload: the id already handed out for ``path``
        starts 404ing, and the next ``filter[name]`` probe issues a fresh one.
        """
        old_id = self._dataref_paths[path]
        self._retired_ids.add(old_id)
        value = self._dataref_values[old_id]
        del self._dataref_paths[path]
        self._add_dataref(path, value)

    def link_toggle(self, press_path: str, status_path: str) -> None:
        """Model the sim's own behaviour: pressing ``press_path`` flips ``status_path``."""
        self._toggle_links[press_path] = status_path

    def link_encoder(self, inc_path: str, dec_path: str, read_path: str, step: float) -> None:
        self._encoder_links[inc_path] = (read_path, step)
        self._encoder_links[dec_path] = (read_path, -step)

    def force_stuck_value(self, path: str, value: Any) -> None:
        """Every subsequent read of ``path`` returns ``value``, regardless of writes —
        the drum-echo shape research §5 warns about."""
        self._stuck[self._dataref_paths[path]] = value

    def value_of(self, path: str) -> Any:
        return self._dataref_values[self._dataref_paths[path]]

    def activated_paths(self) -> list[str]:
        return [self._id_history[command_id] for command_id in self.activated]

    # -- HTTP ------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        query = parse_qs(url.query)

        if url.path == "/api/v2/datarefs":
            filter_name = query.get("filter[name]", [None])[0]
            if filter_name is not None:
                self.probed_names.append(filter_name)
                return self._filtered_response(
                    filter_name, self._dataref_paths, "invalid_dataref_name"
                )
            self.full_index_requests += 1
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"name": path, "id": self._dataref_paths[path]}
                        for path in self._core_dataref_names
                        if path in self._dataref_paths
                    ]
                },
            )

        if url.path == "/api/v2/commands":
            filter_name = query.get("filter[name]", [None])[0]
            self.probed_names.append(filter_name or "")
            return self._filtered_response(
                filter_name or "", self._command_paths, "invalid_command_name"
            )

        if url.path.startswith("/api/v2/datarefs/") and url.path.endswith("/value"):
            dataref_id = int(url.path.split("/")[-2])
            if request.method == "GET":
                return self._read_dataref(dataref_id)
            if request.method == "PATCH":
                body = json.loads(request.content)
                index = query.get("index", [None])[0]
                return self._write_dataref(
                    dataref_id, body["data"], int(index) if index is not None else None
                )

        if url.path.startswith("/api/v2/command/") and url.path.endswith("/activate"):
            command_id = int(url.path.split("/")[-2])
            return self._activate_command(command_id)

        return httpx.Response(404, json={"error": url.path})  # pragma: no cover - a test bug

    def _filtered_response(
        self, name: str, paths: dict[str, int], miss_code: str
    ) -> httpx.Response:
        if not name or name in self._unavailable or name not in paths:
            return httpx.Response(
                404,
                json={"error_code": miss_code, "error_message": f"{name!r} doesn't exist"},
            )
        resolved_id = paths[name]
        return httpx.Response(200, json={"data": [{"name": name, "id": resolved_id}]})

    def _read_dataref(self, dataref_id: int) -> httpx.Response:
        if dataref_id in self._retired_ids:
            return httpx.Response(
                404,
                json={"error_code": "invalid_dataref_id", "error_message": "no such dataref id"},
            )
        if dataref_id in self._stuck:
            return httpx.Response(200, json={"data": self._stuck[dataref_id]})
        return httpx.Response(200, json={"data": self._dataref_values[dataref_id]})

    def _write_dataref(self, dataref_id: int, value: Any, index: int | None) -> httpx.Response:
        if dataref_id in self._retired_ids:
            return httpx.Response(
                404,
                json={"error_code": "invalid_dataref_id", "error_message": "no such dataref id"},
            )
        self.writes.append((dataref_id, value, index))
        if index is None:
            self._dataref_values[dataref_id] = value
        else:
            current = self._dataref_values[dataref_id]
            array = list(current) if isinstance(current, list) else []
            while len(array) <= index:
                array.append(0)
            array[index] = value
            self._dataref_values[dataref_id] = array
        return httpx.Response(200, json={"data": None})

    def _activate_command(self, command_id: int) -> httpx.Response:
        if command_id in self._retired_ids:
            return httpx.Response(
                404,
                json={"error_code": "invalid_command_id", "error_message": "no such command id"},
            )
        self.activated.append(command_id)
        path = self._id_history[command_id]
        if path in self._toggle_links:
            status_path = self._toggle_links[path]
            status_id = self._dataref_paths[status_path]
            self._dataref_values[status_id] = not bool(self._dataref_values[status_id])
        elif path in self._encoder_links:
            read_path, delta = self._encoder_links[path]
            read_id = self._dataref_paths[read_path]
            current = self._dataref_values[read_id]
            self._dataref_values[read_id] = float(current) + delta
        return httpx.Response(200, json={"data": None})


def _fake_trainer_api() -> _FakeWebApi:
    """A ``_FakeWebApi`` that publishes exactly the bindings
    ``tests/core/fixtures/cockpit/fake-trainer`` declares.
    """
    api = _FakeWebApi()
    api.publish_dataref("fake/cockpit/present", 1)

    for control_id, initial in (
        ("fd_capt", False),
        ("cmd_a", False),
        ("hdg_sel", False),
        ("battery", True),
        ("landing_lights", False),
    ):
        press = f"fake/{control_id}/press"
        status = f"fake/{control_id}/status"
        api.publish_command(press)
        api.publish_dataref(status, initial)
        api.link_toggle(press, status)

    api.publish_command("fake/toga/press")
    api.publish_command("fake/chime_test/press")

    api.publish_dataref("fake/mcp_alt/dial", 5000.0)
    api.publish_dataref("fake/mcp_hdg/dial", 90.0)
    api.publish_dataref("fake/irs_l/pos", 0)

    api.publish_command("fake/stab_trim/inc")
    api.publish_command("fake/stab_trim/dec")
    api.publish_dataref("fake/stab_trim/pos", 4.0)
    api.link_encoder("fake/stab_trim/inc", "fake/stab_trim/dec", "fake/stab_trim/pos", 0.5)

    return api


def _script(monkeypatch: pytest.MonkeyPatch, api: _FakeWebApi) -> None:
    real_client = httpx.AsyncClient

    def build_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        del args
        return real_client(
            base_url=str(kwargs.get("base_url", "")),
            transport=httpx.MockTransport(api.handle),
        )

    monkeypatch.setattr(httpx, "AsyncClient", build_client)


async def _connected(
    monkeypatch: pytest.MonkeyPatch,
    catalog_root: Path,
    api: _FakeWebApi | None = None,
) -> tuple[XPlaneSimAdapter, _FakeWebApi]:
    api = api or _fake_trainer_api()
    _script(monkeypatch, api)
    monkeypatch.setattr(cockpit_controls, "COCKPIT_CATALOGS_DIR", catalog_root)
    # No live sim to give a frame or two to — the ordering under test does
    # not depend on the gap, only the attempt count.
    monkeypatch.setattr(cockpit_controls, "COCKPIT_READBACK_GAP_S", 0.0)
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    return adapter, api


# --------------------------------------------------------------------------
# Detection (D5)
# --------------------------------------------------------------------------


async def test_detection_probes_by_name_and_never_the_full_index(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        # connect() itself issues one unfiltered scan (DATAREFS/OPTIONAL_DATAREFS)
        # and the unrelated traffic-bridge probe issues its own — both settled
        # before this point. What matters is that NEITHER cockpit detection
        # NOR any actuation below adds another one.
        index_requests_after_connect = api.full_index_requests

        catalog = await adapter.get_cockpit_catalog()
        assert catalog.supported is True
        assert catalog.aircraft is not None
        assert catalog.aircraft.catalog_id == "fake-trainer"
        assert catalog.revision == 1
        assert catalog.reason is None
        assert "fake/cockpit/present" in api.probed_names

        await adapter.actuate_cockpit_control(CockpitActuation(control_id="fd_capt", value=True))
        assert api.full_index_requests == index_requests_after_connect
    finally:
        await adapter.disconnect()


async def test_a_build_without_the_detection_dataref_reports_no_catalog(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    api = _FakeWebApi()  # fake/cockpit/present never published
    adapter, _ = await _connected(monkeypatch, catalog_root, api)
    try:
        catalog = await adapter.get_cockpit_catalog()
        assert catalog.supported is True
        assert catalog.aircraft is None
        assert catalog.reason is not None
        assert "No cockpit catalog matched the loaded aircraft" in catalog.reason
        assert catalog.revision == 1
        assert catalog.panels == []
        assert catalog.controls == []
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# Lazy binding resolution (D6)
# --------------------------------------------------------------------------


async def test_binding_resolution_is_lazy_and_cached(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        await adapter.get_cockpit_catalog()
        assert "fake/fd_capt/press" not in api.probed_names
        assert "fake/fd_capt/status" not in api.probed_names

        await adapter.actuate_cockpit_control(CockpitActuation(control_id="fd_capt", value=True))
        assert api.probed_names.count("fake/fd_capt/press") == 1
        assert api.probed_names.count("fake/fd_capt/status") == 1

        await adapter.actuate_cockpit_control(CockpitActuation(control_id="fd_capt", value=False))
        # Cached: the second actuation resolves neither binding again.
        assert api.probed_names.count("fake/fd_capt/press") == 1
        assert api.probed_names.count("fake/fd_capt/status") == 1
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# Per-kind execution (D2, D8, §5.5)
# --------------------------------------------------------------------------


async def test_toggle_presses_only_when_the_state_disagrees(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        flipped = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="fd_capt", value=True)
        )
        assert flipped.state.value is True
        assert flipped.actions_taken == 1
        assert api.activated_paths() == ["fake/fd_capt/press"]

        unchanged = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="fd_capt", value=True)
        )
        assert unchanged.actions_taken == 0
        assert api.activated_paths() == ["fake/fd_capt/press"]  # no new press
    finally:
        await adapter.disconnect()


async def test_dial_writes_and_confirms(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        result = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="mcp_alt", value=6000.0)
        )
        assert result.state.value == 6000.0
        assert result.actions_taken == 1
        assert api.value_of("fake/mcp_alt/dial") == 6000.0
    finally:
        await adapter.disconnect()


async def test_a_dial_write_that_never_confirms_is_rejected(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    api.force_stuck_value("fake/mcp_alt/dial", 5000.0)  # never reflects the write
    try:
        with pytest.raises(CockpitWriteRejected, match="mcp_alt"):
            await adapter.actuate_cockpit_control(
                CockpitActuation(control_id="mcp_alt", value=6000.0)
            )
    finally:
        await adapter.disconnect()


async def test_encoder_fires_inc_or_dec_and_reports_the_moved_value(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        before = len(api.activated)
        up = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="stab_trim", delta=2)
        )
        assert up.state.value == pytest.approx(5.0)
        assert len(api.activated) - before == 2
        assert api.activated_paths()[-2:] == ["fake/stab_trim/inc", "fake/stab_trim/inc"]

        before = len(api.activated)
        down = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="stab_trim", delta=-2)
        )
        assert down.state.value == pytest.approx(4.0)
        assert len(api.activated) - before == 2
        assert api.activated_paths()[-2:] == ["fake/stab_trim/dec", "fake/stab_trim/dec"]
    finally:
        await adapter.disconnect()


async def test_press_control_fires_once_and_reports_no_state(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        result = await adapter.actuate_cockpit_control(CockpitActuation(control_id="toga"))
        assert result.actions_taken == 1
        assert result.state.value is None
        assert api.activated_paths() == ["fake/toga/press"]
    finally:
        await adapter.disconnect()


async def test_selector_writes_and_confirms(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        result = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="irs_l", value=2)
        )
        assert result.state.value == 2
        assert api.value_of("fake/irs_l/pos") == 2
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# Preconditions (D9)
# --------------------------------------------------------------------------


async def test_precondition_unmet_blocks_the_write(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        with pytest.raises(CockpitPreconditionUnmet, match="flight director"):
            await adapter.actuate_cockpit_control(
                CockpitActuation(control_id="hdg_sel", value=True)
            )
        assert api.activated == []

        await adapter.actuate_cockpit_control(CockpitActuation(control_id="fd_capt", value=True))
        result = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="hdg_sel", value=True)
        )
        assert result.state.value is True
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# The aircraft-change hook (D7)
# --------------------------------------------------------------------------


async def test_a_changed_acf_relative_path_re_detects(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        first = await adapter.get_cockpit_catalog()
        assert first.revision == 1
        assert first.aircraft is not None

        api.set_acf_relative_path("Aircraft/Other/other.acf")
        api.unpublish("fake/cockpit/present")

        second = await adapter.get_cockpit_catalog()
        assert second.revision == 2
        assert second.aircraft is None

        with pytest.raises(CockpitCatalogInactive):
            await adapter.actuate_cockpit_control(
                CockpitActuation(control_id="fd_capt", value=True)
            )
    finally:
        await adapter.disconnect()


async def test_a_retired_binding_id_triggers_one_re_detect_and_retry(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        await adapter.actuate_cockpit_control(CockpitActuation(control_id="fd_capt", value=True))
        revision_before = (await adapter.get_cockpit_catalog()).revision

        api.retire_dataref("fake/fd_capt/status")

        result = await adapter.actuate_cockpit_control(
            CockpitActuation(control_id="fd_capt", value=False)
        )
        assert result.state.value is False

        revision_after = (await adapter.get_cockpit_catalog()).revision
        assert revision_after == revision_before + 1
    finally:
        await adapter.disconnect()


async def test_missing_acf_relative_path_reprobes_every_call(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    api = _fake_trainer_api()
    api.set_acf_relative_path(None)
    adapter, _ = await _connected(monkeypatch, catalog_root, api)
    try:
        count_before = api.probed_names.count("fake/cockpit/present")
        await adapter.get_cockpit_catalog()
        await adapter.get_cockpit_catalog()
        count_after = api.probed_names.count("fake/cockpit/present")
        assert count_after == count_before + 2
    finally:
        await adapter.disconnect()


async def test_refresh_cockpit_catalog_bumps_the_revision(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, _ = await _connected(monkeypatch, catalog_root)
    try:
        before = await adapter.get_cockpit_catalog()
        after = await adapter.refresh_cockpit_catalog()
        assert after.revision == before.revision + 1
        assert after.aircraft is not None
        assert after.aircraft.catalog_id == "fake-trainer"
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# AircraftSetup through the catalog (D11, §5.6)
# --------------------------------------------------------------------------


async def test_apply_setup_routes_covered_fields_through_the_catalog(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        await adapter.apply_setup(AircraftSetup(autopilot_hdg=True, flight_director=True))

        # fd_capt (the precondition) before hdg_sel — never the generic
        # autopilot_mode dataref or a lateral-mode command.
        assert api.activated_paths() == ["fake/fd_capt/press", "fake/hdg_sel/press"]
        assert api.value_of("fake/fd_capt/status") is True
        assert api.value_of("fake/hdg_sel/status") is True

        autopilot_mode_id = next(
            dataref_id
            for path, dataref_id in api._dataref_paths.items()
            if path == DATAREFS["autopilot_mode"]
        )
        assert all(written_id != autopilot_mode_id for written_id, _, _ in api.writes)
    finally:
        await adapter.disconnect()


async def test_apply_setup_falls_through_to_the_generic_path_for_uncovered_fields(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    """``target_ias_kt`` has no ``setup_overrides`` entry in ``fake-trainer`` —
    it must still reach the generic autopilot dataref writes."""
    adapter, api = await _connected(monkeypatch, catalog_root)
    try:
        await adapter.apply_setup(AircraftSetup(target_ias_kt=250.0))
        assert api.value_of(DATAREFS["autopilot_airspeed_dial"]) == 250.0
    finally:
        await adapter.disconnect()


async def test_apply_setup_without_a_catalog_is_unaffected(
    monkeypatch: pytest.MonkeyPatch, catalog_root: Path
) -> None:
    """No catalog detected -> the cockpit hook is a no-op; the stock 737's own
    autopilot path (research-verified, pre-existing) is unchanged."""
    api = _FakeWebApi()  # fake/cockpit/present never published
    adapter, dataref_api = await _connected(monkeypatch, catalog_root, api)
    try:
        await adapter.apply_setup(AircraftSetup(autopilot_hdg=True, flight_director=True))
        assert dataref_api.value_of(DATAREFS["autopilot_mode"]) != 0
        # The lateral-mode command fired, the generic path's own signature.
        assert COMMANDS["autopilot_heading"] in dataref_api.activated_paths()
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# _lookup_id (§5.2, the generalised sibling of #217's fix)
# --------------------------------------------------------------------------


async def test_lookup_id_returns_none_on_a_404_for_datarefs() -> None:
    def miss(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            404,
            json={"error_code": "invalid_dataref_name", "error_message": "doesn't exist"},
        )

    async with httpx.AsyncClient(
        base_url="http://x", transport=httpx.MockTransport(miss)
    ) as client:
        result = await cockpit_controls._lookup_id(client, "datarefs", "sim/does/not/exist")
    assert result is None


async def test_lookup_id_still_raises_on_a_server_error_for_datarefs() -> None:
    def blow_up(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, json={"error_code": "internal", "error_message": "boom"})

    async with httpx.AsyncClient(
        base_url="http://x", transport=httpx.MockTransport(blow_up)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await cockpit_controls._lookup_id(client, "datarefs", "sim/whatever")


def test_split_index_parses_the_array_element_suffix() -> None:
    assert cockpit_controls._split_index("laminar/B738/ap/nav_status[0]") == (
        "laminar/B738/ap/nav_status",
        0,
    )
    assert cockpit_controls._split_index("laminar/B738/autopilot/mcp_alt_dial") == (
        "laminar/B738/autopilot/mcp_alt_dial",
        None,
    )


# --------------------------------------------------------------------------
# The shipped catalog files — the CI gate Wave 2's data PRs run against (§8.4)
# --------------------------------------------------------------------------


def test_every_shipped_catalog_directory_loads_and_is_well_formed() -> None:
    documents, errors = load_all_catalogs(cockpit_controls.COCKPIT_CATALOGS_DIR)
    assert errors == ()
    assert documents, "no catalog directory under adapters/xplane/cockpit_catalogs/ loaded"

    today = date.today()
    for document in documents:
        for control in document.controls:
            assert control.verified_on <= today
            for path in (
                control.binding.press,
                control.binding.read,
                control.binding.write,
                control.binding.inc,
                control.binding.dec,
            ):
                if path is None:
                    continue
                base_path, _ = cockpit_controls._split_index(path)
                assert base_path.startswith(("sim/", "laminar/")), (
                    f"{document.aircraft.catalog_id}: {control.control_id!r} binds an "
                    f"unrecognised namespace {base_path!r}"
                )


def test_zibo_b738_root_declares_its_read_back_confirmed_detection_dataref() -> None:
    documents, errors = load_all_catalogs(cockpit_controls.COCKPIT_CATALOGS_DIR)
    assert errors == ()
    zibo = next(document for document in documents if document.aircraft.catalog_id == "zibo-b738")
    assert zibo.detect.dataref_exists == "laminar/B738/autopilot/mcp_alt_dial"
    # Wave 2 (#222) supplies the MCP panel's controls
    # (docs/designs/cockpit-control-catalog.md §5.7) — the remaining panels
    # (overhead, pedestal, lights) are #223/#224, still empty here.
    assert {control.control_id for control in zibo.controls} == {
        "fd_capt",
        "fd_fo",
        "cmd_a",
        "cmd_b",
        "ap_disconnect",
        "hdg_sel",
        "vorloc",
        "app",
        "mcp_alt",
        "mcp_hdg",
        "mcp_speed",
    }
    assert {control.control_id for control in zibo.parked} == {
        "mcp_vs",
        "ias_mach_changeover",
        "lnav",
    }
    assert {panel.panel_id for panel in zibo.panels} == {"mcp", "overhead", "pedestal", "lights"}
    assert zibo.setup_overrides == {
        "flight_director": "fd_capt",
        "autopilot_master": "cmd_a",
        "autopilot_hdg": "hdg_sel",
        "autopilot_nav": "vorloc",
        "autopilot_app": "app",
        "target_altitude_ft": "mcp_alt",
        "target_heading_deg": "mcp_hdg",
        "target_ias_kt": "mcp_speed",
    }


async def test_cockpit_runtime_reports_the_mcp_panel_controls_for_zibo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sanity check against the REAL shipped directory (not the
    ``fake-trainer`` fixture): detecting the Zibo now reports the MCP panel's
    controls (#222), with the overhead/pedestal/lights panels still empty
    (#223/#224). Deliberately does NOT monkeypatch ``COCKPIT_CATALOGS_DIR`` —
    this is the one test that exercises the real
    ``adapters/xplane/cockpit_catalogs/`` tree end to end.
    """
    api = _FakeWebApi()
    api.publish_dataref("laminar/B738/autopilot/mcp_alt_dial", 5000.0)
    _script(monkeypatch, api)
    monkeypatch.setattr(cockpit_controls, "COCKPIT_READBACK_GAP_S", 0.0)
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        catalog = await adapter.get_cockpit_catalog()
        assert catalog.aircraft is not None
        assert catalog.aircraft.catalog_id == "zibo-b738"
        assert len(catalog.controls) == 11
        assert len(catalog.parked) == 3
        assert all(control.panel_id == "mcp" for control in catalog.controls)
        assert all(control.panel_id == "mcp" for control in catalog.parked)
    finally:
        await adapter.disconnect()
