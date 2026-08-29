"""Unit tests for ``core.fuel_payload.models`` — the request/result vocabulary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.fuel_payload.models import FUEL_PAYLOAD_PRESETS, FuelPayloadRequest
from core.models import Loadout, TankFuel


class TestFuelPayloadPresetCatalogue:
    def test_every_preset_id_is_in_the_catalogue(self) -> None:
        assert set(FUEL_PAYLOAD_PRESETS) == {"ferry", "training", "full", "empty"}

    def test_the_four_presets_match_the_design_table(self) -> None:
        assert FUEL_PAYLOAD_PRESETS["empty"].fuel_fraction == 0.0
        assert FUEL_PAYLOAD_PRESETS["empty"].station_fraction == 0.0
        assert FUEL_PAYLOAD_PRESETS["training"].fuel_fraction == 0.5
        assert FUEL_PAYLOAD_PRESETS["training"].station_fraction == 0.10
        assert FUEL_PAYLOAD_PRESETS["ferry"].fuel_fraction == 1.0
        assert FUEL_PAYLOAD_PRESETS["ferry"].station_fraction == 0.0
        assert FUEL_PAYLOAD_PRESETS["full"].fuel_fraction == 1.0
        assert FUEL_PAYLOAD_PRESETS["full"].station_fraction == 1.0


class TestFuelPayloadRequest:
    def test_neither_preset_nor_loadout_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must carry a preset, a loadout, or both"):
            FuelPayloadRequest()

    def test_preset_alone_is_accepted(self) -> None:
        FuelPayloadRequest(preset="training")

    def test_loadout_alone_is_accepted(self) -> None:
        FuelPayloadRequest(loadout=Loadout(tanks=[TankFuel(tank_index=0, fuel_kg=10.0)]))

    def test_both_together_is_accepted(self) -> None:
        FuelPayloadRequest(preset="training", loadout=Loadout(tanks=[]))

    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            FuelPayloadRequest.model_validate({"preset": "training", "bogus": 1})

    def test_override_envelope_defaults_false(self) -> None:
        assert FuelPayloadRequest(preset="empty").override_envelope is False
