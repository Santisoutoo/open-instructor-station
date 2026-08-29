"""Catalogue-integrity tests for the shipped scenario directory
(``core/scenarios/data/``) — mirrors ``core.weather.presets``'s own
``TestPresetCatalogueIntegrity`` shape (``tests/core/weather/test_presets.py``),
per ``docs/designs/scenario-generator.md`` D14/§2.1/§8.1.

**Note on ``core.scenarios.loader``:** that module is Track A's own file
(``docs/designs/scenario-generator.md`` §9) and may not exist yet on this
branch when this test is authored. Importing it here — and every test in
this module — is expected to fail with a ``ModuleNotFoundError`` until
Track A's ``core/scenarios/loader.py`` lands; that combination step is not
this track's responsibility. This module is written correctly against the
design regardless, so it goes green the moment both tracks are on the
branch together.
"""

from __future__ import annotations

from core.scenarios.loader import load_all_scenarios
from core.scenarios.preflight import missing_capabilities
from core.sim_adapter import Capabilities

#: Pinned explicitly, not computed from the directory listing — a shipped
#: file added, renamed or removed without updating this list fails loudly.
#: The fourteen files for the feature spec's twelve named exercises (D14).
EXPECTED_SCENARIO_IDS: tuple[str, ...] = (
    "bird-strike",
    "crosswind-landing",
    "electrical-failure",
    "engine-failure-after-v1",
    "go-around",
    "hydraulic-failure",
    "low-visibility-cat-i",
    "low-visibility-cat-ii",
    "low-visibility-cat-iii",
    "rejected-takeoff",
    "tailwind-landing",
    "tcas-resolution-advisory",
    "unstable-approach",
    "wind-shear",
)

_ALL_CAPABILITIES_TRUE = Capabilities(
    can_set_position=True,
    can_set_aircraft_state=True,
    can_set_weather=True,
    can_inject_failures=True,
    can_spawn_traffic=True,
    can_control_autopilot=True,
    can_set_fuel_payload=True,
    can_control_camera=True,
    can_pushback=True,
)

_ALL_CAPABILITIES_TRUE_EXCEPT_TRAFFIC = _ALL_CAPABILITIES_TRUE.model_copy(
    update={"can_spawn_traffic": False}
)


class TestShippedScenarioCatalogueIntegrity:
    """The real shipped directory (core/scenarios/data/), zero cache, no
    fixture directory involved — exactly what GET /api/scenarios re-parses
    on every call (D12)."""

    def test_loads_with_zero_errors(self) -> None:
        _loaded, errors = load_all_scenarios()
        assert errors == ()

    def test_ids_match_the_pinned_fourteen_exactly(self) -> None:
        loaded, errors = load_all_scenarios()
        assert errors == ()
        assert sorted(scenario.id for scenario in loaded) == sorted(EXPECTED_SCENARIO_IDS)
        assert len(EXPECTED_SCENARIO_IDS) == 14


class TestShippedScenarioPreflight:
    """Every shipped document is at least *checkable* without raising, and
    only the TCAS scenario needs can_spawn_traffic — D11's live example of
    per-scenario, not per-manager, capability gating."""

    def test_every_scenario_has_no_missing_capabilities_when_all_are_true(self) -> None:
        loaded, errors = load_all_scenarios()
        assert errors == ()
        for scenario in loaded:
            assert missing_capabilities(scenario.document, _ALL_CAPABILITIES_TRUE) == (), (
                scenario.id
            )

    def test_only_tcas_needs_traffic_capability(self) -> None:
        loaded, errors = load_all_scenarios()
        assert errors == ()
        missing_by_id = {
            scenario.id: missing_capabilities(
                scenario.document, _ALL_CAPABILITIES_TRUE_EXCEPT_TRAFFIC
            )
            for scenario in loaded
        }
        non_empty = {scenario_id: flags for scenario_id, flags in missing_by_id.items() if flags}
        assert non_empty == {"tcas-resolution-advisory": ("can_spawn_traffic",)}
