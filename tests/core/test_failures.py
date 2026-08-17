"""Unit tests for ``core.failures`` — the catalogue, refs and triggers.

No simulator, no adapter: catalogue integrity is a drift guard, everything
else is a pure pydantic construction.
"""

from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from core.failures import (
    CATALOGUE_BY_ID,
    FAILURE_CATALOGUE,
    FAILURE_IDS,
    ActiveFailure,
    ArmFailureRequest,
    FailureCategory,
    FailureId,
    FailureRef,
    FailureTrigger,
    InjectFailureRequest,
)

#: The ids that take an engine index — pinned explicitly so an accidental
#: flag flip on the catalogue fails a test rather than going unnoticed.
_INDEXED_IDS = frozenset(
    {"engine.failure", "engine.fire", "engine.partial_power", "electrical.generator"}
)

#: The full id set, pinned verbatim: these are the wire format, the YAML
#: format and the profile format — renaming one is a breaking change.
_EXPECTED_IDS = (
    "engine.failure",
    "engine.fire",
    "engine.partial_power",
    "fuel.leak",
    "electrical.system",
    "electrical.generator",
    "hydraulics.system",
    "instruments.pitot",
    "instruments.static",
    "instruments.vacuum",
    "instruments.airspeed",
    "instruments.attitude",
    "instruments.altimeter",
    "instruments.directional_gyro",
    "instruments.turn_coordinator",
    "instruments.vsi",
    "avionics.com1",
    "avionics.com2",
    "avionics.nav1",
    "avionics.nav2",
    "avionics.gps",
    "avionics.transponder",
    "flight_controls.flaps",
    "flight_controls.spoilers",
    "gear.stuck",
    "gear.brakes",
    "airframe.pressurisation",
    "airframe.smoke",
    "airframe.bird_strike",
    "airframe.lightning_strike",
)


class TestCatalogueIntegrity:
    def test_ids_are_pinned_verbatim(self) -> None:
        assert FAILURE_IDS == _EXPECTED_IDS

    def test_literal_and_catalogue_agree(self) -> None:
        """The CONTROL_IDS drift-guard pattern (server/app.py)."""
        assert set(FAILURE_IDS) == {spec.failure_id for spec in FAILURE_CATALOGUE}
        assert set(CATALOGUE_BY_ID) == set(FAILURE_IDS)

    def test_ids_are_unique(self) -> None:
        assert len(FAILURE_IDS) == len(set(FAILURE_IDS))

    def test_ids_are_dotted_lowercase(self) -> None:
        for failure_id in FAILURE_IDS:
            assert failure_id == failure_id.lower()
            assert "." in failure_id

    def test_every_entry_has_a_label_and_description(self) -> None:
        for spec in FAILURE_CATALOGUE:
            assert spec.label
            assert spec.description

    def test_indexed_entries_match_the_pinned_set(self) -> None:
        indexed = {spec.failure_id for spec in FAILURE_CATALOGUE if spec.takes_engine_index}
        assert indexed == _INDEXED_IDS

    def test_categories_are_closed(self) -> None:
        valid_categories = set(get_args(FailureCategory))
        for spec in FAILURE_CATALOGUE:
            assert spec.category in valid_categories


class TestFailureRefValidation:
    def test_indexed_entry_without_index_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="engine index"):
            FailureRef(failure_id="engine.failure")

    def test_non_indexed_entry_with_index_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="does not take an engine index"):
            FailureRef(failure_id="instruments.pitot", engine_index=1)

    def test_indexed_entry_with_index_is_valid(self) -> None:
        ref = FailureRef(failure_id="engine.fire", engine_index=2)
        assert ref.engine_index == 2

    def test_non_indexed_entry_without_index_is_valid(self) -> None:
        ref = FailureRef(failure_id="hydraulics.system")
        assert ref.engine_index is None

    def test_engine_index_out_of_range_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            FailureRef(failure_id="engine.failure", engine_index=9)

    def test_unknown_failure_id_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            FailureRef.model_validate({"failure_id": "not.a.real.failure"})

    def test_extra_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            FailureRef.model_validate({"failure_id": "hydraulics.system", "extra_field": "nope"})

    def test_is_frozen(self) -> None:
        ref = FailureRef(failure_id="hydraulics.system")
        with pytest.raises(ValidationError):
            ref.engine_index = 1


class TestRequestSubclasses:
    def test_inject_failure_request_carries_no_extra_fields(self) -> None:
        request = InjectFailureRequest(failure_id="airframe.smoke")
        assert request.failure_id == "airframe.smoke"

    def test_active_failure_carries_no_extra_fields(self) -> None:
        active = ActiveFailure(failure_id="gear.brakes")
        assert active.failure_id == "gear.brakes"

    def test_arm_failure_request_carries_a_trigger(self) -> None:
        request = ArmFailureRequest.model_validate(
            {
                "failure_id": "instruments.pitot",
                "trigger": {"type": "altitude_below", "altitude_ft": 3000.0},
            }
        )
        assert request.trigger.type == "altitude_below"


class TestFailureTrigger:
    _trigger_adapter: TypeAdapter[FailureTrigger] = TypeAdapter(FailureTrigger)

    def test_discriminates_on_type(self) -> None:
        trigger = self._trigger_adapter.validate_python({"type": "delay", "delay_s": 5.0})
        assert trigger.type == "delay"
        assert trigger.delay_s == pytest.approx(5.0)

    def test_unknown_type_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            self._trigger_adapter.validate_python({"type": "on_landing", "delay_s": 5.0})

    def test_altitude_above_requires_altitude_ft(self) -> None:
        with pytest.raises(ValidationError):
            self._trigger_adapter.validate_python({"type": "altitude_above"})

    def test_speed_below_accepts_a_valid_value(self) -> None:
        trigger = self._trigger_adapter.validate_python({"type": "speed_below", "ias_kt": 60.0})
        assert trigger.type == "speed_below"
        assert trigger.ias_kt == pytest.approx(60.0)

    def test_delay_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            self._trigger_adapter.validate_python({"type": "delay", "delay_s": 0.0})

    def test_extra_field_on_a_trigger_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            self._trigger_adapter.validate_python(
                {"type": "delay", "delay_s": 5.0, "extra": "nope"}
            )


def test_get_args_matches_failure_ids() -> None:
    assert get_args(FailureId) == FAILURE_IDS
