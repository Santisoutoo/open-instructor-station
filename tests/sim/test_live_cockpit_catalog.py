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
from core.cockpit.models import CockpitActuation, CockpitCatalogDocument, CockpitControlDefinition
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
        try:
            flipped = await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=not original_bool)
            )
            assert flipped.state.value == (not original_bool)
        finally:
            await live_adapter.actuate_cockpit_control(
                CockpitActuation(control_id=spec.control_id, value=original_bool)
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
