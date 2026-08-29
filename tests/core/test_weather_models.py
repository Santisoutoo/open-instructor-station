"""Unit tests for ``core.weather.models`` — the layer/state/setup validators.

No simulator, no adapter: every case here is a pure pydantic construction.
"""

import pytest
from pydantic import ValidationError

from core.weather.models import CloudLayer, WeatherSetup, WeatherState, WindLayer


def _wind(altitude_ft: float) -> WindLayer:
    return WindLayer(altitude_ft=altitude_ft, direction_deg=270.0, speed_kt=10.0)


def _cloud(base_ft: float, tops_ft: float) -> CloudLayer:
    return CloudLayer(base_ft=base_ft, tops_ft=tops_ft, coverage_ratio=0.5)


class TestCloudLayer:
    def test_tops_must_exceed_base(self) -> None:
        with pytest.raises(ValidationError, match="tops_ft"):
            CloudLayer(base_ft=2000.0, tops_ft=2000.0, coverage_ratio=0.5)

    def test_tops_below_base_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CloudLayer(base_ft=2000.0, tops_ft=1000.0, coverage_ratio=0.5)

    def test_valid_layer_constructs(self) -> None:
        layer = _cloud(1000.0, 3000.0)
        assert layer.cloud_type == "cumulus"


class TestWeatherStateLayerValidation:
    def test_at_most_three_wind_layers(self) -> None:
        with pytest.raises(ValidationError, match="At most 3 wind layers"):
            _state(wind_layers=[_wind(0.0), _wind(1000.0), _wind(2000.0), _wind(3000.0)])

    def test_at_most_three_cloud_layers(self) -> None:
        with pytest.raises(ValidationError, match="At most 3 cloud layers"):
            _state(
                cloud_layers=[
                    _cloud(0.0, 500.0),
                    _cloud(1000.0, 1500.0),
                    _cloud(2000.0, 2500.0),
                    _cloud(3000.0, 3500.0),
                ]
            )

    def test_wind_layers_must_be_sorted_ascending(self) -> None:
        with pytest.raises(ValidationError, match="sorted ascending"):
            _state(wind_layers=[_wind(5000.0), _wind(0.0)])

    def test_cloud_layers_must_be_sorted_ascending(self) -> None:
        with pytest.raises(ValidationError, match="sorted ascending"):
            _state(cloud_layers=[_cloud(3000.0, 4000.0), _cloud(1000.0, 2000.0)])

    def test_wind_layers_within_100ft_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="within 100 ft"):
            _state(wind_layers=[_wind(0.0), _wind(50.0)])

    def test_cloud_layers_within_100ft_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="within 100 ft"):
            _state(cloud_layers=[_cloud(1000.0, 2000.0), _cloud(1050.0, 2050.0)])

    def test_layers_exactly_100ft_apart_are_accepted(self) -> None:
        state = _state(wind_layers=[_wind(0.0), _wind(100.0)])
        assert len(state.wind_layers) == 2

    def test_empty_layer_lists_are_valid(self) -> None:
        state = _state(wind_layers=[], cloud_layers=[])
        assert state.wind_layers == []
        assert state.cloud_layers == []


class TestWeatherStateDewpointClamp:
    def test_dewpoint_above_temperature_is_clamped_on_construction(self) -> None:
        state = _state(temperature_c=10.0, dewpoint_c=15.0)
        assert state.dewpoint_c == pytest.approx(10.0)

    def test_dewpoint_at_or_below_temperature_is_left_alone(self) -> None:
        state = _state(temperature_c=10.0, dewpoint_c=5.0)
        assert state.dewpoint_c == pytest.approx(5.0)


class TestWeatherSetupDewpointRefusal:
    def test_dewpoint_above_temperature_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="dewpoint_c"):
            WeatherSetup(temperature_c=10.0, dewpoint_c=15.0)

    def test_dewpoint_at_temperature_is_accepted(self) -> None:
        setup = WeatherSetup(temperature_c=10.0, dewpoint_c=10.0)
        assert setup.dewpoint_c == pytest.approx(10.0)

    def test_only_one_of_the_pair_never_triggers_the_check(self) -> None:
        setup = WeatherSetup(dewpoint_c=25.0)
        assert setup.dewpoint_c == pytest.approx(25.0)


class TestWeatherSetupSparseSemantics:
    def test_everything_defaults_to_none(self) -> None:
        setup = WeatherSetup()
        assert setup.model_dump(exclude_none=True) == {}

    def test_empty_list_survives_exclude_none(self) -> None:
        setup = WeatherSetup(cloud_layers=[])
        dumped = setup.model_dump(exclude_none=True)
        assert dumped["cloud_layers"] == []

    def test_layer_list_validators_also_apply_to_the_setup(self) -> None:
        with pytest.raises(ValidationError, match="sorted ascending"):
            WeatherSetup(wind_layers=[_wind(5000.0), _wind(0.0)])

    def test_none_layers_skip_validation_entirely(self) -> None:
        setup = WeatherSetup(wind_layers=None)
        assert setup.wind_layers is None


class TestModelsAreFrozen:
    def test_wind_layer_is_frozen(self) -> None:
        layer = _wind(0.0)
        with pytest.raises(ValidationError):
            layer.speed_kt = 99.0

    def test_weather_state_is_frozen(self) -> None:
        state = _state()
        with pytest.raises(ValidationError):
            state.qnh_hpa = 999.0

    def test_weather_setup_is_frozen(self) -> None:
        setup = WeatherSetup(qnh_hpa=1000.0)
        with pytest.raises(ValidationError):
            setup.qnh_hpa = 999.0


def _state(**overrides: object) -> WeatherState:
    defaults: dict[str, object] = {
        "wind_layers": [],
        "cloud_layers": [],
        "visibility_m": 10_000.0,
        "qnh_hpa": 1013.25,
        "temperature_c": 15.0,
        "dewpoint_c": 5.0,
        "precipitation_ratio": 0.0,
        "runway_contamination": "dry",
    }
    defaults.update(overrides)
    return WeatherState.model_validate(defaults)
