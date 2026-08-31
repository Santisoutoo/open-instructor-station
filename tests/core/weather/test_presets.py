"""Unit tests for ``core.weather.presets`` and the model additions it builds on.

No simulator, no navdata provider — every case here is pure pydantic
construction plus ``resolve_preset``/``merge_setup``/``resolve_request``
called with plain numbers, exactly as weather-manager.md §9.1 specifies.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from core.weather.models import (
    PresetCloudLayer,
    PresetWindLayer,
    WeatherPreset,
    WeatherPresetId,
    WeatherRequest,
    WeatherSetup,
)
from core.weather.presets import WEATHER_PRESETS, merge_setup, resolve_preset, resolve_request

#: The fixture world's field, shared with tests/server/conftest.py's ZZZZ:
#: elevation 1000 ft, runway 36 true bearing 000°.
ZZZZ_ELEVATION_FT = 1000.0
ZZZZ_RUNWAY_36_BEARING_DEG = 0.0


# ---------------------------------------------------------------------------
# Model validation — PresetWindLayer / PresetCloudLayer / WeatherRequest
# ---------------------------------------------------------------------------


class TestPresetWindLayerDirectionSource:
    def test_neither_direction_nor_offset_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="Exactly one"):
            PresetWindLayer(altitude_agl_ft=0.0, speed_kt=10.0)

    def test_both_direction_and_offset_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="Exactly one"):
            PresetWindLayer(
                altitude_agl_ft=0.0,
                direction_deg=90.0,
                offset_from_runway_deg=90.0,
                speed_kt=10.0,
            )

    def test_direction_alone_is_accepted(self) -> None:
        layer = PresetWindLayer(altitude_agl_ft=0.0, direction_deg=270.0, speed_kt=10.0)
        assert layer.direction_deg == 270.0

    def test_offset_alone_is_accepted(self) -> None:
        layer = PresetWindLayer(altitude_agl_ft=0.0, offset_from_runway_deg=90.0, speed_kt=10.0)
        assert layer.offset_from_runway_deg == 90.0


class TestPresetCloudLayerValidation:
    def test_tops_must_exceed_base(self) -> None:
        with pytest.raises(ValidationError, match="tops_agl_ft"):
            PresetCloudLayer(
                base_agl_ft=250.0, tops_agl_ft=250.0, coverage_ratio=1.0, cloud_type="stratus"
            )

    def test_valid_layer_constructs(self) -> None:
        layer = PresetCloudLayer(
            base_agl_ft=250.0, tops_agl_ft=2500.0, coverage_ratio=1.0, cloud_type="stratus"
        )
        assert layer.tops_agl_ft == 2500.0


class TestWeatherRequestValidation:
    def test_neither_preset_nor_setup_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="preset, a setup, or both"):
            WeatherRequest()

    def test_preset_alone_is_accepted(self) -> None:
        request = WeatherRequest(preset="cavok")
        assert request.setup is None

    def test_setup_alone_is_accepted(self) -> None:
        request = WeatherRequest(setup=WeatherSetup(visibility_m=1000.0))
        assert request.preset is None

    def test_unknown_extra_field_is_refused(self) -> None:
        """The scenario-YAML typo case: ``extra='forbid'`` must fail loudly."""
        with pytest.raises(ValidationError):
            WeatherRequest.model_validate({"preset": "cavok", "wnid": "wrong"})

    def test_unknown_preset_id_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            WeatherRequest.model_validate({"preset": "hurricane"})

    def test_is_frozen(self) -> None:
        request = WeatherRequest(preset="cavok")
        with pytest.raises(ValidationError):
            request.preset = "storm"


# ---------------------------------------------------------------------------
# resolve_preset — geometry
# ---------------------------------------------------------------------------


class TestResolvePresetWindGeometry:
    def test_crosswind_at_runway_bearing_000(self) -> None:
        setup, _notes = resolve_preset(
            WEATHER_PRESETS["crosswind"],
            runway_true_bearing_deg=0.0,
            field_elevation_ft=ZZZZ_ELEVATION_FT,
        )
        assert setup.wind_layers is not None
        assert len(setup.wind_layers) == 1
        assert setup.wind_layers[0].direction_deg == pytest.approx(90.0)
        assert setup.wind_layers[0].speed_kt == pytest.approx(20.0)
        assert setup.wind_layers[0].gust_increase_kt == pytest.approx(5.0)

    def test_crosswind_at_runway_bearing_233(self) -> None:
        setup, _notes = resolve_preset(
            WEATHER_PRESETS["crosswind"],
            runway_true_bearing_deg=233.0,
            field_elevation_ft=ZZZZ_ELEVATION_FT,
        )
        assert setup.wind_layers is not None
        assert setup.wind_layers[0].direction_deg == pytest.approx(323.0)

    def test_negative_offset_at_runway_bearing_000(self) -> None:
        preset = WeatherPreset(
            id="crosswind",
            label="Crosswind (left)",
            description="test fixture",
            wind_layers=(
                PresetWindLayer(altitude_agl_ft=0.0, offset_from_runway_deg=-90.0, speed_kt=20.0),
            ),
        )
        setup, _notes = resolve_preset(
            preset, runway_true_bearing_deg=0.0, field_elevation_ft=ZZZZ_ELEVATION_FT
        )
        assert setup.wind_layers is not None
        assert setup.wind_layers[0].direction_deg == pytest.approx(270.0)

    def test_crosswind_layer_altitude_is_field_elevation(self) -> None:
        setup, _notes = resolve_preset(
            WEATHER_PRESETS["crosswind"],
            runway_true_bearing_deg=0.0,
            field_elevation_ft=ZZZZ_ELEVATION_FT,
        )
        assert setup.wind_layers is not None
        assert setup.wind_layers[0].altitude_ft == pytest.approx(ZZZZ_ELEVATION_FT)


class TestResolvePresetCloudGeometry:
    def test_cat_i_at_field_elevation_1000ft(self) -> None:
        setup, _notes = resolve_preset(WEATHER_PRESETS["cat_i"], field_elevation_ft=1000.0)
        assert setup.cloud_layers is not None
        layer = setup.cloud_layers[0]
        assert layer.base_ft == pytest.approx(1250.0)
        assert layer.tops_ft == pytest.approx(3500.0)

    def test_cat_i_at_negative_field_elevation_does_not_clamp(self) -> None:
        """Schiphol-like -11 ft: a negative elevation must not clamp to zero."""
        setup, _notes = resolve_preset(WEATHER_PRESETS["cat_i"], field_elevation_ft=-11.0)
        assert setup.cloud_layers is not None
        assert setup.cloud_layers[0].base_ft == pytest.approx(239.0)


class TestResolvePresetMountainWave:
    def test_middle_layer_at_zzzz_elevation(self) -> None:
        setup, _notes = resolve_preset(
            WEATHER_PRESETS["mountain_wave"], field_elevation_ft=ZZZZ_ELEVATION_FT
        )
        assert setup.wind_layers is not None
        assert len(setup.wind_layers) == 3
        assert setup.wind_layers[1].altitude_ft == pytest.approx(9000.0)

    def test_absolute_direction_needs_no_runway_bearing(self) -> None:
        # mountain_wave states absolute directions; no bearing is passed at all.
        setup, _notes = resolve_preset(
            WEATHER_PRESETS["mountain_wave"], field_elevation_ft=ZZZZ_ELEVATION_FT
        )
        assert setup.wind_layers is not None
        assert all(layer.direction_deg == pytest.approx(270.0) for layer in setup.wind_layers)


class TestResolvePresetRefusals:
    def test_crosswind_without_bearing_raises_naming_the_preset(self) -> None:
        with pytest.raises(ValueError, match="'crosswind'") as excinfo:
            resolve_preset(WEATHER_PRESETS["crosswind"], field_elevation_ft=ZZZZ_ELEVATION_FT)
        assert "runway" in str(excinfo.value)

    def test_cat_i_without_elevation_raises_naming_the_preset(self) -> None:
        with pytest.raises(ValueError, match="'cat_i'") as excinfo:
            resolve_preset(WEATHER_PRESETS["cat_i"], runway_true_bearing_deg=0.0)
        assert "field" in str(excinfo.value)

    def test_cavok_resolves_with_neither(self) -> None:
        setup, _notes = resolve_preset(WEATHER_PRESETS["cavok"])
        assert setup.cloud_layers == []
        assert setup.wind_layers is None


# ---------------------------------------------------------------------------
# merge_setup
# ---------------------------------------------------------------------------


class TestMergeSetup:
    def test_override_visibility_over_resolved_cat_i(self) -> None:
        resolved, _notes = resolve_preset(WEATHER_PRESETS["cat_i"], field_elevation_ft=1000.0)
        merged = merge_setup(resolved, WeatherSetup(visibility_m=1200.0))
        assert merged.visibility_m == pytest.approx(1200.0)
        # Everything else the preset stated survives the overlay untouched.
        assert merged.temperature_c == pytest.approx(12.0)

    def test_empty_cloud_layers_overlay_clears_storm(self) -> None:
        resolved, _notes = resolve_preset(WEATHER_PRESETS["storm"], field_elevation_ft=1000.0)
        assert resolved.cloud_layers
        merged = merge_setup(resolved, WeatherSetup(cloud_layers=[]))
        assert merged.cloud_layers == []

    def test_merged_result_is_a_validated_weather_setup(self) -> None:
        base = WeatherSetup(temperature_c=10.0)
        overlay = WeatherSetup(dewpoint_c=5.0)
        merged = merge_setup(base, overlay)
        assert isinstance(merged, WeatherSetup)
        assert merged.temperature_c == pytest.approx(10.0)
        assert merged.dewpoint_c == pytest.approx(5.0)

    def test_merge_revalidates_and_refuses_an_inconsistent_result(self) -> None:
        """An overlay that makes the combined state self-contradictory is refused.

        ``merge_setup`` goes through ``model_validate`` rather than
        ``model_copy(update=...)`` precisely so a merged result that violates a
        cross-field validator (dewpoint above temperature) cannot survive to
        the adapter — the position router's merge-bug lesson, pinned here.
        """
        base = WeatherSetup(temperature_c=10.0)
        overlay = WeatherSetup(dewpoint_c=25.0)
        with pytest.raises(ValidationError, match="dewpoint_c"):
            merge_setup(base, overlay)


# ---------------------------------------------------------------------------
# Notes provenance
# ---------------------------------------------------------------------------


class TestNotesProvenance:
    def test_crosswind_note_carries_offset_and_bearing(self) -> None:
        _setup, notes = resolve_preset(
            WEATHER_PRESETS["crosswind"], runway_true_bearing_deg=0.0, field_elevation_ft=1000.0
        )
        joined = " ".join(notes)
        assert "90" in joined  # the offset
        assert "000" in joined  # the runway's true bearing

    def test_override_produces_a_your_override_sentence(self) -> None:
        request = WeatherRequest(preset="cat_i", setup=WeatherSetup(visibility_m=1200.0))
        _setup, notes = resolve_request(request, field_elevation_ft=1000.0)
        assert any("your override" in note for note in notes)
        assert any("visibility_m" in note for note in notes)


# ---------------------------------------------------------------------------
# resolve_request
# ---------------------------------------------------------------------------


class TestResolveRequest:
    def test_setup_only_request_is_used_verbatim(self) -> None:
        setup = WeatherSetup(visibility_m=5000.0)
        request = WeatherRequest(setup=setup)
        resolved, notes = resolve_request(request)
        assert resolved == setup
        assert notes == ()

    def test_preset_only_request_resolves_the_preset(self) -> None:
        request = WeatherRequest(preset="cavok")
        resolved, _notes = resolve_request(request)
        assert resolved.visibility_m == pytest.approx(20_000.0)

    def test_preset_with_override_merges_and_notes(self) -> None:
        request = WeatherRequest(preset="cat_i", setup=WeatherSetup(visibility_m=1200.0))
        resolved, notes = resolve_request(request, field_elevation_ft=1000.0)
        assert resolved.visibility_m == pytest.approx(1200.0)
        assert notes  # provenance is not silently dropped

    def test_preset_needing_context_still_raises_through_resolve_request(self) -> None:
        request = WeatherRequest(preset="crosswind")
        with pytest.raises(ValueError, match="'crosswind'"):
            resolve_request(request)


# ---------------------------------------------------------------------------
# Preset catalogue integrity
# ---------------------------------------------------------------------------


#: weather-manager.md §4's table, restated as the expectation this test pins.
_EXPECTED_REQUIREMENTS: dict[WeatherPresetId, tuple[bool, bool]] = {
    # preset_id: (requires_runway, requires_airport)
    "cavok": (False, False),
    "cat_i": (False, True),
    "cat_ii": (False, True),
    "cat_iii": (False, True),
    "storm": (False, True),
    "crosswind": (True, True),
    "mountain_wave": (False, True),
}


class TestPresetCatalogueIntegrity:
    def test_every_preset_id_has_an_entry(self) -> None:
        assert set(WEATHER_PRESETS) == set(get_args(WeatherPresetId))

    @pytest.mark.parametrize("preset_id", get_args(WeatherPresetId))
    def test_requirements_match_the_design_table(self, preset_id: WeatherPresetId) -> None:
        preset = WEATHER_PRESETS[preset_id]
        expected_runway, expected_airport = _EXPECTED_REQUIREMENTS[preset_id]
        assert preset.requires_runway is expected_runway
        assert preset.requires_airport is expected_airport

    def test_cat_presets_state_saturated_air(self) -> None:
        """dewpoint == temperature in every CAT preset (fog/stratus is a zero spread)."""
        for preset_id in ("cat_i", "cat_ii", "cat_iii"):
            setup = WEATHER_PRESETS[preset_id].setup
            assert setup.temperature_c == setup.dewpoint_c

    def test_crosswind_states_wind_and_nothing_else(self) -> None:
        preset = WEATHER_PRESETS["crosswind"]
        assert preset.cloud_layers is None
        assert preset.setup.model_dump(exclude_none=True) == {}
