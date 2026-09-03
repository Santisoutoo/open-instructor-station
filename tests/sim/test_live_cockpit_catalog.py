"""The cockpit control catalog against a live X-Plane. Never runs in CI.

Per ``docs/designs/cockpit-control-catalog.md`` §8.5. Run with a simulator
loaded and its Web API enabled::

    pytest -m sim tests/sim/test_live_cockpit_catalog.py
    pytest -m sim tests/sim/test_live_cockpit_catalog.py -k "zibo-b738::mcp"   # one panel

**The honest resolution of the "a capability flag that gates its own
validation is a deadlock" gotcha** (CLAUDE.md's "Known gotchas"):
``can_control_cockpit`` is already ``True`` (Wave 1 Track B, §5.2) — the flip
asserts the detection/resolution/execution MACHINERY is right, structurally,
not that it has been flown. This suite is what settles the live half.
:func:`test_detection_matches_the_loaded_aircraft` FAILS LOUDLY, never skips,
when the loaded aircraft's ``acf_relative_path`` matches a catalog's
``path_hints`` but the live probe did not detect it — the exact case a
mis-flipped flag would otherwise hide.

The per-entry sweep is parametrised at COLLECTION time (module import, YAML
read only, no adapter needed) over every ``controls[*]`` of every catalog
directory under ``adapters/xplane/cockpit_catalogs/``, so
``pytest -m sim ... -k "<catalog-id>::<panel-id>"`` scopes one panel for
``sim-validator``'s serialised per-PR pass (§8.4/§9.3, D15). Wave 1 Track B
ships the Zibo's ``aircraft.yaml`` with zero controls, so this sweep collects
zero cases today — it starts finding work the moment Wave 2 (#222-#224)
lands a panel file, with no code change here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import NamedTuple

import pytest

from adapters.xplane import cockpit_controls
from adapters.xplane.xplane_adapter import XPlaneSimAdapter
from core.cockpit.catalog import load_all_catalogs
from core.cockpit.errors import CockpitPreconditionUnmet
from core.cockpit.models import (
    CockpitActuation,
    CockpitCatalogDocument,
    CockpitControlDefinition,
    CockpitControlSpec,
)
from core.models import AircraftSetup

pytestmark = pytest.mark.sim


class _SweepEntry(NamedTuple):
    catalog_id: str
    panel_id: str
    control: CockpitControlDefinition


def _collect_sweep_entries() -> tuple[_SweepEntry, ...]:
    """Every catalogued control, read straight from the YAML — no adapter,
    no network. Errors are not swallowed here: a directory that fails to
    load is exactly what ``tests/adapters/test_xplane_cockpit.py``'s catalog
    smoke test already catches in CI, so this collector trusts it.
    """
    documents, _errors = load_all_catalogs(cockpit_controls.COCKPIT_CATALOGS_DIR)
    return tuple(
        _SweepEntry(document.aircraft.catalog_id, control.panel_id, control)
        for document in documents
        for control in document.controls
    )


_SWEEP_ENTRIES = _collect_sweep_entries()
_SWEEP_PARAMS = [
    pytest.param(entry, id=f"{entry.catalog_id}::{entry.panel_id}::{entry.control.control_id}")
    for entry in _SWEEP_ENTRIES
]


@pytest.fixture
async def live_adapter() -> AsyncIterator[XPlaneSimAdapter]:
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        yield adapter
    finally:
        await adapter.disconnect()


def _catalog_documents() -> tuple[CockpitCatalogDocument, ...]:
    documents, _errors = load_all_catalogs(cockpit_controls.COCKPIT_CATALOGS_DIR)
    return documents


async def test_detection_matches_the_loaded_aircraft(live_adapter: XPlaneSimAdapter) -> None:
    """The deadlock-breaking assertion (module docstring): a live install
    whose loaded aircraft LOOKS like a catalogued one but was not detected
    fails here, loudly — never a skip. ``path_hints`` (§3.2) exist for
    exactly this: a live test that can tell "nothing matched" apart from
    "something matched and the probe missed it".
    """
    assert live_adapter.capabilities.can_control_cockpit is True

    path = await live_adapter._read_acf_relative_path()  # the diagnostic escape hatch
    catalog = await live_adapter.get_cockpit_catalog()

    documents = _catalog_documents()
    looks_like: list[str] = []
    if path is not None:
        looks_like = [
            document.aircraft.catalog_id
            for document in documents
            if any(hint in path for hint in document.aircraft.path_hints)
        ]

    if not looks_like:
        assert catalog.aircraft is None, (
            f"the loaded aircraft path {path!r} matches no catalog's path_hints, but the "
            f"adapter detected {catalog.aircraft!r} anyway"
        )
        assert catalog.reason
        return

    assert catalog.aircraft is not None, (
        f"the loaded aircraft path {path!r} looks like {looks_like!r} (path_hints), but "
        "the live detection probe did not confirm it — either the detection dataref is "
        "wrong, or the aircraft installed does not match what path_hints claims"
    )
    assert catalog.aircraft.catalog_id in looks_like


async def _arm_unmet_preconditions(
    live_adapter: XPlaneSimAdapter, spec: CockpitControlSpec
) -> list[tuple[str, bool]]:
    """Generic, aircraft-agnostic precondition satisfier for the sweep (D9):
    for every unmet ``any_of`` group on ``spec``, actuate the FIRST referenced
    control to the value the group needs, and remember its prior state so the
    caller can put it back. Never touches a group member beyond the first —
    catalog authors are expected to list the most reliably-restorable control
    first in ``any_of`` (``mcp.yaml`` lists ``fd_capt`` before ``cmd_a``/
    ``cmd_b`` for exactly this reason: CMD A/B only disengage through a
    separate control, so the sweep must never be the one that arms them).
    A no-op, returning ``[]``, when every group is already satisfied.
    """
    restore: list[tuple[str, bool]] = []
    for group in spec.preconditions:
        states = {
            condition.control_id: (await live_adapter.read_cockpit_states([condition.control_id]))
            .states[0]
            .value
            for condition in group.any_of
        }
        if any(states[condition.control_id] == condition.equals for condition in group.any_of):
            continue
        guard = group.any_of[0]
        before_guard = bool(states[guard.control_id])
        await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id=guard.control_id, value=guard.equals)
        )
        restore.append((guard.control_id, before_guard))
    return restore


@pytest.mark.parametrize("entry", _SWEEP_PARAMS)
async def test_the_generic_live_sweep(live_adapter: XPlaneSimAdapter, entry: _SweepEntry) -> None:
    """Flip it, read it back, put it back — by kind (§8.5). Every restore in
    a ``finally``. Run on the ground, parked (``tests/conftest.py``'s session
    fixture applies): this file adds no fixture of its own for that.
    """
    catalog = await live_adapter.get_cockpit_catalog()
    if catalog.aircraft is None or catalog.aircraft.catalog_id != entry.catalog_id:
        pytest.skip(f"{entry.catalog_id!r} is not the active cockpit catalog on this install")

    spec_by_id = {spec.control_id: spec for spec in catalog.controls}
    spec = spec_by_id.get(entry.control.control_id)
    if spec is None:
        pytest.skip(
            f"{entry.control.control_id!r} is not in the live manifest for "
            f"{entry.catalog_id!r} (parked, or a catalog mismatch)"
        )
    if not spec.live_sweep:
        pytest.skip(spec.live_sweep_note or f"{spec.control_id!r} is marked live_sweep=False")

    if spec.kind == "toggle":
        before = (await live_adapter.read_cockpit_states([spec.control_id])).states[0].value
        original_bool = bool(before)
        # Arm whatever this control's own preconditions need (research §2's
        # ordering finding) so a lateral-mode entry (hdg_sel/vorloc/app) can
        # actually be swept, not just the FD/CMD toggles that gate it.
        guard_restore = await _arm_unmet_preconditions(live_adapter, spec)
        try:
            flipped = await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=not original_bool)
            )
            assert flipped.state.value == (not original_bool)
        finally:
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=original_bool)
            )
            for guard_id, guard_before in reversed(guard_restore):
                await live_adapter.actuate_cockpit_control(
                    CockpitActuation(control_id=guard_id, value=guard_before)
                )

    elif spec.kind == "dial":
        assert spec.min_value is not None
        assert spec.max_value is not None
        assert spec.step is not None
        before_dial = (await live_adapter.read_cockpit_states([spec.control_id])).states[0].value
        assert isinstance(before_dial, (int, float)) and not isinstance(before_dial, bool)
        original_dial = float(before_dial)
        dial_target = (
            original_dial + spec.step
            if original_dial + spec.step <= spec.max_value
            else original_dial - spec.step
        )
        try:
            result = await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=dial_target)
            )
            assert result.state.value == pytest.approx(dial_target, abs=spec.readback_tolerance)
        finally:
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=original_dial)
            )

    elif spec.kind == "selector":
        assert spec.options is not None
        option_values = [option.value for option in spec.options]
        before_selector = (
            (await live_adapter.read_cockpit_states([spec.control_id])).states[0].value
        )
        assert isinstance(before_selector, (int, str))
        current_index = option_values.index(before_selector)
        selector_target = option_values[(current_index + 1) % len(option_values)]
        try:
            result = await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=selector_target)
            )
            assert result.state.value == selector_target
        finally:
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=before_selector)
            )

    elif spec.kind == "encoder":
        try:
            up = await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, delta=1)
            )
            if spec.readable:
                assert up.state.value is not None
        finally:
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, delta=-1)
            )

    else:  # press — only ever reached when live_sweep is True (guarded above)
        result = await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id=spec.control_id)
        )
        assert result.actions_taken == 1


async def test_zibo_hdg_sel_needs_a_flight_director_or_cmd_before_it_arms(
    live_adapter: XPlaneSimAdapter,
) -> None:
    """#222's ordering precondition (research §2): the lateral-mode presses
    (``hdg_sel`` here) are inert unless a flight director or CMD is already
    on, and this must be encoded as a precondition group (D9), not merely as
    field order — enforced here BEFORE anything is written
    (``CockpitPreconditionUnmet``, no activation), and satisfied once one of
    the guard toggles is engaged.
    """
    catalog = await live_adapter.get_cockpit_catalog()
    if catalog.aircraft is None or catalog.aircraft.catalog_id != "zibo-b738":
        pytest.skip("zibo-b738 is not the active cockpit catalog on this install")

    # Clear every guard toggle first: ap_disconnect for cmd_a/cmd_b (a single
    # press turns both off at once, cheaper than two guarded round trips),
    # fd_capt/fd_fo individually below (all four are genuine bidirectional
    # toggles, mcp.yaml's settle_s note).
    await live_adapter.actuate_cockpit_control(CockpitActuation(control_id="ap_disconnect"))
    fd_guard_ids = ("fd_capt", "fd_fo")
    before_fd_guards = {
        control_id: bool((await live_adapter.read_cockpit_states([control_id])).states[0].value)
        for control_id in fd_guard_ids
    }
    for control_id, value in before_fd_guards.items():
        if value:
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=control_id, value=False)
            )

    try:
        with pytest.raises(CockpitPreconditionUnmet) as unmet:
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id="hdg_sel", value=True)
            )
        assert "flight director" in str(unmet.value).lower() or "cmd" in str(unmet.value).lower()

        # Nothing was written: the press never reached the sim.
        still_off = (await live_adapter.read_cockpit_states(["hdg_sel"])).states[0].value
        assert not bool(still_off)

        # Satisfy the group with one guard toggle and retry — now it arms.
        await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id="fd_capt", value=True)
        )
        armed = await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id="hdg_sel", value=True)
        )
        assert armed.state.value is True
    finally:
        current_hdg_sel = (await live_adapter.read_cockpit_states(["hdg_sel"])).states[0].value
        if bool(current_hdg_sel):
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id="hdg_sel", value=False)
            )
        for control_id, value in before_fd_guards.items():
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=control_id, value=value)
            )


async def test_zibo_airspeed_dial_confirms_from_its_own_dataref_not_the_drum_echo(
    live_adapter: XPlaneSimAdapter,
) -> None:
    """Research §5's read-back gotcha: ``mcp_speed_dial_kts2`` and
    ``mcp_speed_dial_kts_mach`` are slow, separately-updating echoes of the
    physical dial drum and must never be what confirms a write. The
    catalog's ``mcp_speed`` entry designates ``mcp_speed_dial_kts`` itself as
    the read binding (``mcp.yaml``) — this asserts the confirmed write comes
    back immediately (no settle wait beyond the entry's own ``settle_s``),
    and separately reads the echo dataref through the SAME resolver
    (``CockpitRuntime._read_binding``, the real code path, not a hand-rolled
    HTTP call) purely to prove the distinct dataref genuinely exists and
    resolves — not to assert it lags, which would make this test flaky.
    """
    catalog = await live_adapter.get_cockpit_catalog()
    if catalog.aircraft is None or catalog.aircraft.catalog_id != "zibo-b738":
        pytest.skip("zibo-b738 is not the active cockpit catalog on this install")

    before = (await live_adapter.read_cockpit_states(["mcp_speed"])).states[0].value
    assert isinstance(before, int | float) and not isinstance(before, bool)
    original = float(before)
    target = original + 40.0 if original + 40.0 <= 340.0 else original - 40.0

    try:
        result = await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id="mcp_speed", value=target)
        )
        # Confirmed by the designated (fast) binding, immediately.
        assert result.state.value == pytest.approx(target, abs=0.0)

        # The slow-echo dataref must still resolve through the same runtime —
        # proves the distinction is a real, live-verified dataref, not a typo.
        echo = await live_adapter._cockpit._read_binding(
            live_adapter, "laminar/B738/autopilot/mcp_speed_dial_kts2"
        )
        assert echo is not None
    finally:
        await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id="mcp_speed", value=original)
        )


async def test_zibo_setup_overrides_deliver_the_autopilot_fields_via_apply_setup(
    live_adapter: XPlaneSimAdapter,
) -> None:
    """The user-facing bug #214 uncovered, closed by this catalog's
    ``setup_overrides`` (D11): ``apply_setup`` must actually move the Zibo's
    MCP, not silently accept a write the flight model ignores. Exercises the
    real ``AircraftSetup`` -> ``_write_autopilot`` ->
    ``_apply_cockpit_setup_overrides`` -> ``plan_setup_actuations`` path, in
    precondition order (FD before the lateral mode — research §2), and
    read-back-confirms every field through the catalog's own controls.
    """
    catalog = await live_adapter.get_cockpit_catalog()
    if catalog.aircraft is None or catalog.aircraft.catalog_id != "zibo-b738":
        pytest.skip("zibo-b738 is not the active cockpit catalog on this install")

    tracked_ids = ("fd_capt", "hdg_sel", "mcp_alt", "mcp_hdg")
    before = {
        control_id: (await live_adapter.read_cockpit_states([control_id])).states[0].value
        for control_id in tracked_ids
    }
    assert isinstance(before["mcp_alt"], int | float)
    assert isinstance(before["mcp_hdg"], int | float)
    target_altitude = 4000.0 if float(before["mcp_alt"]) != 4000.0 else 5000.0
    target_heading = (float(before["mcp_hdg"]) + 20.0) % 360.0

    try:
        # A single AircraftSetup carries FD + lateral mode + two dials in one
        # call — apply_setup must apply FD/master before the lateral-mode
        # press (not field-declaration order) for HDG SEL to actually arm.
        await live_adapter.apply_setup(
            AircraftSetup(
                flight_director=True,
                autopilot_hdg=True,
                target_altitude_ft=target_altitude,
                target_heading_deg=target_heading,
            )
        )

        fd_state = (await live_adapter.read_cockpit_states(["fd_capt"])).states[0].value
        hdg_sel_state = (await live_adapter.read_cockpit_states(["hdg_sel"])).states[0].value
        alt_state = (await live_adapter.read_cockpit_states(["mcp_alt"])).states[0].value
        hdg_state = (await live_adapter.read_cockpit_states(["mcp_hdg"])).states[0].value

        assert fd_state is True
        assert hdg_sel_state is True
        assert alt_state == pytest.approx(target_altitude, abs=0.0)
        assert hdg_state == pytest.approx(target_heading, abs=0.0)

        # autopilot_master=True (-> cmd_a) must also be DELIVERED through
        # apply_setup — the exact bug #214 reported ("the master/FD ladder
        # dataref never moves at all"). Restored via ap_disconnect in the
        # finally below, which also clears cmd_b's channel for free.
        await live_adapter.apply_setup(AircraftSetup(autopilot_master=True))
        cmd_a_state = (await live_adapter.read_cockpit_states(["cmd_a"])).states[0].value
        assert cmd_a_state is True
    finally:
        await live_adapter.actuate_cockpit_control(CockpitActuation(control_id="ap_disconnect"))
        current_hdg_sel = (await live_adapter.read_cockpit_states(["hdg_sel"])).states[0].value
        if bool(current_hdg_sel):
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id="hdg_sel", value=False)
            )
        await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id="mcp_alt", value=float(before["mcp_alt"]))
        )
        await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id="mcp_hdg", value=float(before["mcp_hdg"]))
        )
        await live_adapter.actuate_cockpit_control(
            CockpitActuation(control_id="fd_capt", value=bool(before["fd_capt"]))
        )


async def test_stock_aircraft_has_no_catalog_and_generic_setup_still_works(
    live_adapter: XPlaneSimAdapter,
) -> None:
    """Only meaningful when the loaded aircraft matches no catalog (#222's
    stock-737 acceptance): the generic autopilot path — pre-existing,
    research-verified — must be completely unaffected by this manager
    existing on the adapter at all.
    """
    catalog = await live_adapter.get_cockpit_catalog()
    if catalog.aircraft is not None:
        pytest.skip(
            f"{catalog.aircraft.catalog_id!r} is active on this install — the generic path "
            "is exercised, and possibly overridden, by the catalog; nothing to prove here"
        )

    state = await live_adapter.get_aircraft_state()
    try:
        # Accepting the write is the assertion, the test_apply_setup_writes_the_autopilot
        # precedent (tests/adapters/test_contract.py): a selector X-Plane will not take
        # comes back as an HTTP error, not a shrug.
        await live_adapter.apply_setup(
            AircraftSetup(autopilot_hdg=True, target_heading_deg=(state.heading_deg + 10.0) % 360.0)
        )
    finally:
        await live_adapter.apply_setup(AircraftSetup(autopilot_hdg=False))
