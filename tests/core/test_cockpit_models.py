"""Unit tests for ``core.cockpit.models`` (docs/designs/cockpit-control-catalog.md §3, §8.1).

Written before the implementation exists (Wave 1 Track A of #220): every test
here is expected to fail with ``ModuleNotFoundError`` until ``core/cockpit/``
is built. That failure is the deliverable, not a bug in this file.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from core.cockpit.models import (
    CockpitActuation,
    CockpitControlSpec,
    SelectorOption,
)

VERIFIED_ON = datetime.date(2026, 9, 2)


def _spec(kind: str, **overrides: object) -> CockpitControlSpec:
    """A minimally valid ``CockpitControlSpec`` of ``kind``, overridable per test.

    ``readable`` is filled with the value the per-kind table (§3.1) documents
    for a control of this kind constructed with a plausible binding: ``True``
    for toggle/dial/selector, ``False`` for press, ``True`` for encoder (an
    encoder's readability is binding-dependent — either is legal, so a test
    that cares picks explicitly).
    """
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
        base.update(unit="ft", min_value=0.0, max_value=100.0, step=10.0)
    elif kind == "encoder":
        base.update(unit="units", step=1.0, max_delta=10)
    elif kind == "selector":
        base["options"] = [
            SelectorOption(value=0, label="Off"),
            SelectorOption(value=1, label="On"),
        ]
    base.update(overrides)
    return CockpitControlSpec.model_validate(base)


# ---------------------------------------------------------------------------
# CockpitActuation — the "one intent" rule
# ---------------------------------------------------------------------------


def test_actuation_carrying_both_value_and_delta_raises() -> None:
    with pytest.raises(ValidationError):
        CockpitActuation(control_id="x", value=1, delta=1)


def test_actuation_with_only_value_is_valid() -> None:
    actuation = CockpitActuation(control_id="x", value=True)
    assert actuation.value is True
    assert actuation.delta is None


def test_actuation_with_only_delta_is_valid() -> None:
    actuation = CockpitActuation(control_id="x", delta=-2)
    assert actuation.delta == -2
    assert actuation.value is None


def test_actuation_with_neither_is_valid_a_press() -> None:
    actuation = CockpitActuation(control_id="x")
    assert actuation.value is None
    assert actuation.delta is None


# ---------------------------------------------------------------------------
# CockpitControlSpec — every kind constructs minimally
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["toggle", "press", "dial", "encoder", "selector"])
def test_minimal_valid_spec_constructs_for_every_kind(kind: str) -> None:
    _spec(kind)


# ---------------------------------------------------------------------------
# toggle — §3.1's per-kind table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["unit", "min_value", "max_value", "step", "max_delta", "options"],
)
def test_toggle_forbids_dial_and_selector_fields(field: str) -> None:
    value: object = (
        "ft"
        if field == "unit"
        else ([SelectorOption(value=0, label="Off")] if field == "options" else 1.0)
    )
    with pytest.raises(ValidationError):
        _spec("toggle", **{field: value})


# ---------------------------------------------------------------------------
# press — forbids everything a toggle forbids, plus non-default on/off labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["unit", "min_value", "max_value", "step", "max_delta", "options"],
)
def test_press_forbids_dial_and_selector_fields(field: str) -> None:
    value: object = (
        "ft"
        if field == "unit"
        else ([SelectorOption(value=0, label="Off")] if field == "options" else 1.0)
    )
    with pytest.raises(ValidationError):
        _spec("press", **{field: value})


def test_press_forbids_a_non_default_on_label() -> None:
    with pytest.raises(ValidationError):
        _spec("press", on_label="Armed")


def test_press_forbids_a_non_default_off_label() -> None:
    with pytest.raises(ValidationError):
        _spec("press", off_label="Disarmed")


# ---------------------------------------------------------------------------
# dial — required unit/min_value/max_value/step (min < max); forbids
# max_delta/options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("required_field", ["unit", "min_value", "max_value", "step"])
def test_dial_requires_its_own_fields(required_field: str) -> None:
    kwargs: dict[str, object] = {"unit": "ft", "min_value": 0.0, "max_value": 100.0, "step": 10.0}
    del kwargs[required_field]
    with pytest.raises(ValidationError):
        _spec("dial", **kwargs)


def test_dial_rejects_min_not_less_than_max() -> None:
    with pytest.raises(ValidationError):
        _spec("dial", unit="ft", min_value=100.0, max_value=100.0, step=10.0)


@pytest.mark.parametrize("field", ["max_delta", "options"])
def test_dial_forbids_encoder_and_selector_fields(field: str) -> None:
    value: object = 10 if field == "max_delta" else [SelectorOption(value=0, label="Off")]
    with pytest.raises(ValidationError):
        _spec("dial", **{field: value})


# ---------------------------------------------------------------------------
# encoder — required unit/step/max_delta; forbids min_value/max_value/options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("required_field", ["unit", "step", "max_delta"])
def test_encoder_requires_its_own_fields(required_field: str) -> None:
    kwargs: dict[str, object] = {"unit": "units", "step": 1.0, "max_delta": 10}
    del kwargs[required_field]
    with pytest.raises(ValidationError):
        _spec("encoder", **kwargs)


@pytest.mark.parametrize("field", ["min_value", "max_value", "options"])
def test_encoder_forbids_dial_and_selector_fields(field: str) -> None:
    value: object = [SelectorOption(value=0, label="Off")] if field == "options" else 1.0
    with pytest.raises(ValidationError):
        _spec("encoder", **{field: value})


# ---------------------------------------------------------------------------
# selector — required options (unique values, unique labels); forbids
# unit/min_value/max_value/step/max_delta
# ---------------------------------------------------------------------------


def test_selector_requires_options() -> None:
    with pytest.raises(ValidationError):
        _spec("selector", options=None)


def test_selector_rejects_duplicate_option_values() -> None:
    with pytest.raises(ValidationError):
        _spec(
            "selector",
            options=[
                SelectorOption(value=0, label="Off"),
                SelectorOption(value=0, label="Also off"),
            ],
        )


def test_selector_rejects_duplicate_option_labels() -> None:
    with pytest.raises(ValidationError):
        _spec(
            "selector",
            options=[
                SelectorOption(value=0, label="Same"),
                SelectorOption(value=1, label="Same"),
            ],
        )


@pytest.mark.parametrize("field", ["unit", "min_value", "max_value", "step", "max_delta"])
def test_selector_forbids_dial_and_encoder_fields(field: str) -> None:
    value: object = "ft" if field == "unit" else (10 if field == "max_delta" else 1.0)
    with pytest.raises(ValidationError):
        _spec("selector", **{field: value})


# ---------------------------------------------------------------------------
# live_sweep provenance rule (D10)
# ---------------------------------------------------------------------------


def test_live_sweep_false_without_a_note_raises() -> None:
    with pytest.raises(ValidationError):
        _spec("toggle", live_sweep=False)


def test_live_sweep_false_with_a_note_is_valid() -> None:
    spec = _spec("toggle", live_sweep=False, live_sweep_note="Cuts main power.")
    assert spec.live_sweep is False
    assert spec.live_sweep_note == "Cuts main power."


def test_live_sweep_defaults_to_true() -> None:
    spec = _spec("toggle")
    assert spec.live_sweep is True
