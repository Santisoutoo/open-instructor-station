"""The Fake's synthetic cockpit control catalog (D12, §4.1).

A Python constant, not a YAML read — ``FakeSimAdapter`` "performs no I/O
whatsoever" (its own docstring). One control of every kind, one precondition,
one parked entry, so the contract suite covers everything, including an
aircraft swap, in CI.

**This must equal ``load_catalog_dir(tests/core/fixtures/cockpit/fake-trainer)``
field for field.** That fixture is the oracle (its own module docstring): it
was hand-written first, and this constant matches it, never the other way
around. ``tests/core/test_cockpit_catalog.py`` and this module together pin
that with a consistency guard so the YAML fixture and this constant can never
drift apart silently.
"""

from __future__ import annotations

import datetime

from core.cockpit.models import (
    CockpitAircraft,
    CockpitBinding,
    CockpitCatalogDocument,
    CockpitControlDefinition,
    CockpitDetection,
    CockpitPanel,
    CockpitValue,
    ControlCondition,
    ParkedControl,
    PreconditionGroup,
    SelectorOption,
)

__all__ = ["FAKE_COCKPIT_CATALOG", "FAKE_COCKPIT_INITIAL_VALUES"]

_VERIFIED_ON = datetime.date(2026, 9, 2)

_HDG_SEL_PRECONDITIONS = [
    PreconditionGroup(
        any_of=[
            ControlCondition(control_id="fd_capt", equals=True),
            ControlCondition(control_id="cmd_a", equals=True),
        ],
        hint="HDG SEL needs a flight director or CMD A engaged.",
    )
]

FAKE_COCKPIT_CATALOG = CockpitCatalogDocument(
    aircraft=CockpitAircraft(catalog_id="fake-trainer", label="Fake trainer"),
    detect=CockpitDetection(dataref_exists="fake/cockpit/present"),
    panels=[
        CockpitPanel(panel_id="mcp", label="MCP / autopilot", order=0),
        CockpitPanel(panel_id="overhead", label="Overhead", order=1),
        CockpitPanel(panel_id="pedestal", label="Pedestal", order=2),
        CockpitPanel(panel_id="lights", label="Lights", order=3),
    ],
    controls=[
        CockpitControlDefinition(
            control_id="fd_capt",
            label="Flight director (captain)",
            panel_id="mcp",
            kind="toggle",
            readable=True,
            verified_on=_VERIFIED_ON,
            binding=CockpitBinding(press="fake/fd_capt/press", read="fake/fd_capt/status"),
        ),
        CockpitControlDefinition(
            control_id="cmd_a",
            label="CMD A",
            panel_id="mcp",
            kind="toggle",
            readable=True,
            verified_on=_VERIFIED_ON,
            binding=CockpitBinding(press="fake/cmd_a/press", read="fake/cmd_a/status"),
        ),
        CockpitControlDefinition(
            control_id="hdg_sel",
            label="HDG SEL",
            panel_id="mcp",
            kind="toggle",
            readable=True,
            verified_on=_VERIFIED_ON,
            preconditions=_HDG_SEL_PRECONDITIONS,
            binding=CockpitBinding(press="fake/hdg_sel/press", read="fake/hdg_sel/status"),
        ),
        CockpitControlDefinition(
            control_id="mcp_alt",
            label="Altitude",
            panel_id="mcp",
            kind="dial",
            readable=True,
            unit="ft",
            min_value=0.0,
            max_value=50000.0,
            step=100.0,
            readback_tolerance=0.0,
            verified_on=_VERIFIED_ON,
            binding=CockpitBinding(write="fake/mcp_alt/dial"),
        ),
        CockpitControlDefinition(
            control_id="mcp_hdg",
            label="Heading",
            panel_id="mcp",
            kind="dial",
            readable=True,
            unit="deg",
            min_value=0.0,
            max_value=360.0,
            step=1.0,
            verified_on=_VERIFIED_ON,
            binding=CockpitBinding(write="fake/mcp_hdg/dial"),
        ),
        CockpitControlDefinition(
            control_id="battery",
            label="Battery",
            panel_id="overhead",
            kind="toggle",
            readable=True,
            verified_on=_VERIFIED_ON,
            live_sweep=False,
            live_sweep_note="Cutting battery power breaks every later read-back.",
            binding=CockpitBinding(press="fake/battery/press", read="fake/battery/status"),
        ),
        CockpitControlDefinition(
            control_id="irs_l",
            label="IRS L",
            panel_id="overhead",
            kind="selector",
            readable=True,
            options=[
                SelectorOption(value=0, label="OFF"),
                SelectorOption(value=1, label="ALIGN"),
                SelectorOption(value=2, label="NAV"),
                SelectorOption(value=3, label="ATT"),
            ],
            verified_on=_VERIFIED_ON,
            binding=CockpitBinding(read="fake/irs_l/pos", write="fake/irs_l/pos"),
        ),
        CockpitControlDefinition(
            control_id="stab_trim",
            label="Stab trim",
            panel_id="pedestal",
            kind="encoder",
            readable=True,
            unit="units",
            step=0.5,
            max_delta=20,
            verified_on=_VERIFIED_ON,
            binding=CockpitBinding(
                inc="fake/stab_trim/inc", dec="fake/stab_trim/dec", read="fake/stab_trim/pos"
            ),
        ),
        CockpitControlDefinition(
            control_id="toga",
            label="TO/GA",
            panel_id="pedestal",
            kind="press",
            readable=False,
            verified_on=_VERIFIED_ON,
            live_sweep=False,
            live_sweep_note="TO/GA arms thrust; not for a sweep on the ground.",
            binding=CockpitBinding(press="fake/toga/press"),
        ),
        CockpitControlDefinition(
            control_id="landing_lights",
            label="Landing lights",
            panel_id="lights",
            kind="toggle",
            readable=True,
            verified_on=_VERIFIED_ON,
            binding=CockpitBinding(
                press="fake/landing_lights/press", read="fake/landing_lights/status"
            ),
        ),
        CockpitControlDefinition(
            control_id="chime_test",
            label="Chime test",
            panel_id="overhead",
            kind="press",
            readable=False,
            verified_on=_VERIFIED_ON,
            live_sweep=True,
            binding=CockpitBinding(press="fake/chime_test/press"),
        ),
    ],
    parked=[
        ParkedControl(
            control_id="mcp_vs",
            label="V/S",
            panel_id="mcp",
            reason="No settable vertical-speed dataref exists on the reference aircraft "
            "(research §6).",
            since=_VERIFIED_ON,
        )
    ],
    setup_overrides={
        "flight_director": "fd_capt",
        "autopilot_master": "cmd_a",
        "autopilot_hdg": "hdg_sel",
        "target_altitude_ft": "mcp_alt",
        "target_heading_deg": "mcp_hdg",
    },
)

#: Runtime state the loaded document itself carries no opinion on — a
#: catalog schema has no notion of "what value is the switch at right now".
#: Press controls carry no entry (they have no state).
FAKE_COCKPIT_INITIAL_VALUES: dict[str, CockpitValue] = {
    "fd_capt": False,
    "cmd_a": False,
    "hdg_sel": False,
    "mcp_alt": 5000.0,
    "mcp_hdg": 90.0,
    "battery": True,
    "irs_l": 0,
    "stab_trim": 4.0,
    "landing_lights": False,
}
