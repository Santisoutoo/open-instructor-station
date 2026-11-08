"""Unit tests for ``core.cockpit.actuation`` (docs/designs/cockpit-control-catalog.md
§6.2, §8.1).

Written before the implementation exists (Wave 1 Track A of #220): every test
here is expected to fail with ``ModuleNotFoundError`` until ``core/cockpit/``
is built. That failure is the deliverable, not a bug in this file.

``plan_setup_actuations()`` gets particular attention (D11): it ships
data-independent in this foundation slice and #222 (Wave 2) depends on its
ordering being correct without re-implementing it, so every reference value
from §8.1 is pinned here, plus the reversed-declaration-order and
declaration-order-tie-break cases the design's own reasoning implies but does
not spell out as numbers.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from core.cockpit.actuation import (
    dial_confirmed,
    is_on,
    plan_setup_actuations,
    selector_index,
    selector_steps,
    toggle_needs_press,
    validate_actuation,
)
from core.cockpit.catalog import load_catalog_dir
from core.cockpit.models import (
    CockpitActuation,
    CockpitCatalogDocument,
    CockpitControlSpec,
    SelectorOption,
)
from core.models import AircraftSetup

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cockpit"
VERIFIED_ON = datetime.date(2026, 9, 2)


def _fake_trainer_document() -> CockpitCatalogDocument:
    """The loaded ``fake-trainer`` fixture — the real catalog document
    ``plan_setup_actuations`` is meant to be run against, not a hand-rolled
    stand-in, so these tests exercise the loader and the actuation ordering
    against the same facts (docs/designs/cockpit-control-catalog.md §4.1).
    """
    return load_catalog_dir(FIXTURE_DIR / "fake-trainer")


def _spec(kind: str, **overrides: object) -> CockpitControlSpec:
    base: dict[str, object] = {
        "control_id": "x",
        "label": "X",
        "panel_id": "p",
        "kind": kind,
        "verified_on": VERIFIED_ON,
    }
    readable_by_kind = {
        "toggle": True,
        "press": False,
        "dial": True,
        "encoder": True,
        "selector": True,
    }
    base["readable"] = readable_by_kind[kind]
    if kind == "dial":
        base.update(unit="ft", min_value=0.0, max_value=50000.0, step=100.0)
    elif kind == "encoder":
        base.update(unit="units", step=0.5, max_delta=20)
    elif kind == "selector":
        base["options"] = [
            SelectorOption(value=0, label="OFF"),
            SelectorOption(value=1, label="ALIGN"),
            SelectorOption(value=2, label="NAV"),
        ]
    base.update(overrides)
    return CockpitControlSpec.model_validate(base)


# ---------------------------------------------------------------------------
# is_on
# ---------------------------------------------------------------------------


def test_is_on_int_one_matching_on_value() -> None:
    assert is_on(1, 1.0) is True


def test_is_on_within_the_1e6_tolerance() -> None:
    assert is_on(0.9999999, 1.0) is True


def test_is_on_a_string_is_always_false() -> None:
    assert is_on("1", 1.0) is False


def test_is_on_none_is_false() -> None:
    assert is_on(None, 1.0) is False


def test_is_on_a_true_bool_passes_through() -> None:
    assert is_on(True, 1.0) is True


def test_is_on_a_false_bool_passes_through() -> None:
    assert is_on(False, 1.0) is False


# ---------------------------------------------------------------------------
# toggle_needs_press
# ---------------------------------------------------------------------------


def test_toggle_needs_press_already_on_requesting_on_is_false() -> None:
    assert toggle_needs_press(1.0, True, 1.0) is False


def test_toggle_needs_press_currently_off_requesting_on_is_true() -> None:
    assert toggle_needs_press(0, True, 1.0) is True


def test_toggle_needs_press_unknown_current_counts_as_disagreeing() -> None:
    assert toggle_needs_press(None, False, 1.0) is True


def test_toggle_needs_press_already_true_requesting_true_is_false() -> None:
    assert toggle_needs_press(True, True, 1.0) is False


# ---------------------------------------------------------------------------
# dial_confirmed
# ---------------------------------------------------------------------------


def test_dial_confirmed_exact_match() -> None:
    assert dial_confirmed(4000.0, 4000, 0.0) is True


def test_dial_confirmed_the_drum_echo_case() -> None:
    """Research §5's drum echo — the case the read-binding rule exists for."""
    assert dial_confirmed(160.0, 104, 0.0) is False


def test_dial_confirmed_tiny_float_noise_fails_zero_tolerance() -> None:
    assert dial_confirmed(316.0, 316.0000001, 0.0) is False


def test_dial_confirmed_tiny_float_noise_passes_with_tolerance() -> None:
    assert dial_confirmed(316.0, 316.0000001, 0.01) is True


def test_dial_confirmed_a_none_read_is_never_confirmed() -> None:
    assert dial_confirmed(1.0, None, 5.0) is False


# ---------------------------------------------------------------------------
# selector_index / selector_steps
# ---------------------------------------------------------------------------


def test_selector_index_finds_the_value() -> None:
    spec = _spec("selector")
    assert selector_index(spec, 1) == 1


def test_selector_index_missing_value_is_none() -> None:
    spec = _spec("selector")
    assert selector_index(spec, 99) is None


def test_selector_index_matches_a_live_float_readback_against_int_options() -> None:
    """Issue #223 live verification: X-Plane's Web API reports every numeric
    dataref as a JSON float, never a Python int — a `value: 0` option (the
    catalog YAML's natural spelling) must still match a live `0.0` read-back.
    The identical disease #247 fixed for preconditions
    (core.cockpit.preconditions._condition_satisfied), caught here for
    selector_index because issue #223's overhead panel is the first catalog
    with a live `selector` control (mcp.yaml has none)."""
    spec = _spec("selector")
    assert selector_index(spec, 0.0) == 0
    assert selector_index(spec, 1.0) == 1
    assert selector_index(spec, 2.0) == 2


def test_selector_index_never_matches_a_numeric_value_against_a_string_option() -> None:
    spec = _spec(
        "selector",
        options=[SelectorOption(value="OFF", label="Off"), SelectorOption(value="ON", label="On")],
    )
    assert selector_index(spec, 0) is None
    assert selector_index(spec, 0.0) is None


def test_selector_index_never_matches_a_string_value_against_a_numeric_option() -> None:
    spec = _spec("selector")
    assert selector_index(spec, "0") is None


def test_selector_steps_forward() -> None:
    assert selector_steps(0, 3, 4) == 3


def test_selector_steps_backward() -> None:
    assert selector_steps(3, 0, 4) == -3


def test_selector_steps_backward_never_wraps_to_a_short_forward_hop() -> None:
    """A rotary selector has stops: going from index 3 to index 0 on a
    4-option selector is 3 steps back, never +1 the "short way" around."""
    assert selector_steps(3, 0, 4) != 1


def test_selector_steps_no_movement() -> None:
    assert selector_steps(2, 2, 4) == 0


def test_selector_steps_out_of_range_index_raises() -> None:
    with pytest.raises(ValueError, match=r".*"):
        selector_steps(4, 0, 4)


# ---------------------------------------------------------------------------
# validate_actuation — §2.2's table, one case per row
# ---------------------------------------------------------------------------


def test_validate_actuation_rejects_a_bool_for_a_dial() -> None:
    """The bool-is-an-int trap: ``isinstance(True, int)`` is ``True`` in
    Python, so this row exists to catch an implementation that merely checks
    ``isinstance(value, (int, float))``."""
    dial = _spec("dial")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(dial, CockpitActuation(control_id="x", value=True))


def test_validate_actuation_rejects_a_delta_for_a_toggle() -> None:
    toggle = _spec("toggle")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(toggle, CockpitActuation(control_id="x", delta=1))


def test_validate_actuation_rejects_a_value_for_an_encoder() -> None:
    encoder = _spec("encoder")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(encoder, CockpitActuation(control_id="x", value=1.0))


def test_validate_actuation_rejects_a_dial_value_above_max() -> None:
    dial = _spec("dial")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(dial, CockpitActuation(control_id="x", value=50001.0))


def test_validate_actuation_rejects_a_dial_value_below_min() -> None:
    dial = _spec("dial")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(dial, CockpitActuation(control_id="x", value=-1.0))


def test_validate_actuation_accepts_a_dial_value_equal_to_max() -> None:
    dial = _spec("dial")
    validate_actuation(dial, CockpitActuation(control_id="x", value=50000.0))


def test_validate_actuation_does_not_enforce_the_step() -> None:
    """``step`` is a UI hint (§3.1) — X-Plane accepts any value in range."""
    dial = _spec("dial")
    validate_actuation(dial, CockpitActuation(control_id="x", value=3550.0))


def test_validate_actuation_rejects_a_selector_value_not_among_options() -> None:
    selector = _spec("selector")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(selector, CockpitActuation(control_id="x", value=99))


def test_validate_actuation_rejects_a_string_value_when_options_are_ints() -> None:
    """The irs_l case: options are ints; a string value is a mismatch even
    though a selector CAN legitimately carry string option values."""
    selector = _spec("selector")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(selector, CockpitActuation(control_id="x", value="NAV"))


def test_validate_actuation_rejects_a_press_with_a_value() -> None:
    press = _spec("press")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(press, CockpitActuation(control_id="x", value=True))


def test_validate_actuation_rejects_a_press_with_a_delta() -> None:
    press = _spec("press")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(press, CockpitActuation(control_id="x", delta=1))


def test_validate_actuation_accepts_a_bare_press() -> None:
    press = _spec("press")
    validate_actuation(press, CockpitActuation(control_id="x"))


def test_validate_actuation_accepts_an_encoder_delta_at_max_delta() -> None:
    encoder = _spec("encoder")
    validate_actuation(encoder, CockpitActuation(control_id="x", delta=-20))


def test_validate_actuation_rejects_an_encoder_delta_past_max_delta() -> None:
    encoder = _spec("encoder")
    with pytest.raises(ValueError, match=r".*"):
        validate_actuation(encoder, CockpitActuation(control_id="x", delta=-21))


def test_validate_actuation_accepts_a_matching_toggle_value() -> None:
    toggle = _spec("toggle")
    validate_actuation(toggle, CockpitActuation(control_id="x", value=True))


def test_validate_actuation_accepts_a_matching_selector_value() -> None:
    selector = _spec("selector")
    validate_actuation(selector, CockpitActuation(control_id="x", value=1))


# ---------------------------------------------------------------------------
# plan_setup_actuations — D11, the mechanism #222 depends on
# ---------------------------------------------------------------------------


def test_plan_setup_actuations_orders_fd_before_lateral_mode() -> None:
    """§8.1's own pinned value: regardless of ``setup_overrides``
    declaration order, the control referenced by a precondition (``fd_capt``)
    is planned before the control whose precondition names it (``hdg_sel``)."""
    doc = _fake_trainer_document()
    plan = plan_setup_actuations(doc, AircraftSetup(autopilot_hdg=True, flight_director=True))
    assert [(a.control_id, a.value) for a in plan] == [
        ("fd_capt", True),
        ("hdg_sel", True),
    ]


def test_plan_setup_actuations_is_independent_of_setup_overrides_declaration_order() -> None:
    """The ordering comes from the precondition graph, not from the order
    ``setup_overrides`` happens to declare its keys in. Reversing that
    declaration order must not change the result."""
    doc = _fake_trainer_document()
    reversed_doc = doc.model_copy(
        update={"setup_overrides": dict(reversed(doc.setup_overrides.items()))}
    )
    plan = plan_setup_actuations(
        reversed_doc, AircraftSetup(autopilot_hdg=True, flight_director=True)
    )
    assert [(a.control_id, a.value) for a in plan] == [
        ("fd_capt", True),
        ("hdg_sel", True),
    ]


def test_plan_setup_actuations_a_single_dial_field() -> None:
    doc = _fake_trainer_document()
    plan = plan_setup_actuations(doc, AircraftSetup(target_altitude_ft=4000))
    assert len(plan) == 1
    assert plan[0].control_id == "mcp_alt"
    assert plan[0].value == 4000.0
    assert isinstance(plan[0].value, float)


def test_plan_setup_actuations_ties_keep_setup_overrides_declaration_order() -> None:
    """Two dial fields with no precondition relation between them keep the
    order ``setup_overrides`` declares them in: ``target_altitude_ft`` (->
    ``mcp_alt``) before ``target_heading_deg`` (-> ``mcp_hdg``) in the
    fake-trainer fixture's own declaration order."""
    doc = _fake_trainer_document()
    plan = plan_setup_actuations(
        doc, AircraftSetup(target_altitude_ft=4000.0, target_heading_deg=90.0)
    )
    assert [a.control_id for a in plan] == ["mcp_alt", "mcp_hdg"]


def test_plan_setup_actuations_empty_setup_is_empty() -> None:
    doc = _fake_trainer_document()
    assert plan_setup_actuations(doc, AircraftSetup()) == ()


def test_plan_setup_actuations_a_field_with_no_override_is_absent() -> None:
    """``autopilot_nav`` has no entry in the fake-trainer's ``setup_overrides``
    (only ``flight_director``/``autopilot_master``/``autopilot_hdg``/
    ``target_altitude_ft``/``target_heading_deg`` do) — setting it plans
    nothing for it."""
    doc = _fake_trainer_document()
    plan = plan_setup_actuations(doc, AircraftSetup(autopilot_nav=True))
    assert plan == ()


def test_plan_setup_actuations_none_fields_are_untouched() -> None:
    doc = _fake_trainer_document()
    plan = plan_setup_actuations(doc, AircraftSetup(flight_director=None, autopilot_master=True))
    assert [a.control_id for a in plan] == ["cmd_a"]
