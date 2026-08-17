"""The weather vocabulary: layers, the read model, the sparse write model.

Units are aviation-native and live in the field name (docs/designs/weather-manager.md
D13): ``_ft`` feet MSL, ``_kt`` knots, ``_deg`` TRUE degrees, ``_c`` Celsius,
``_hpa`` hectopascals, ``_m`` metres, ratios are dimensionless 0-1.

Layer-list semantics (D3, shared by :class:`WeatherState` and :class:`WeatherSetup`):
at most :data:`MAX_WIND_LAYERS` / :data:`MAX_CLOUD_LAYERS` entries, sorted
ascending by altitude/base, no two layers within 100 ft of each other — a
zero-thickness sandwich is a data error, not a weather.

This module carries only the vocabulary the ``SimAdapter`` contract needs
(D4 of the shared-foundation plan): the preset catalogue, its resolver and the
``WeatherRequest`` model are a later, separate track
(``core/weather/presets.py``) and are not written here.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "MAX_CLOUD_LAYERS",
    "MAX_WIND_LAYERS",
    "CloudLayer",
    "CloudType",
    "RunwayContamination",
    "WeatherPresetId",
    "WeatherSetup",
    "WeatherState",
    "WindLayer",
]

MAX_WIND_LAYERS = 3
MAX_CLOUD_LAYERS = 3

CloudType = Literal["cirrus", "stratus", "cumulus", "cumulonimbus"]

RunwayContamination = Literal["dry", "wet", "puddles", "snow", "ice"]

#: The seven presets the feature spec names. The catalogue itself
#: (``core/weather/presets.py::WEATHER_PRESETS``) is a later, separate track;
#: this closed union is contract vocabulary — the wire format for
#: ``WeatherRequest.preset`` wherever that model ends up living.
WeatherPresetId = Literal[
    "cavok", "cat_i", "cat_ii", "cat_iii", "storm", "crosswind", "mountain_wave"
]


def _validate_wind_layers(layers: list[WindLayer]) -> list[WindLayer]:
    if len(layers) > MAX_WIND_LAYERS:
        raise ValueError(f"At most {MAX_WIND_LAYERS} wind layers, got {len(layers)}.")
    altitudes = [layer.altitude_ft for layer in layers]
    if altitudes != sorted(altitudes):
        raise ValueError("wind_layers must be sorted ascending by altitude_ft.")
    for lower, upper in pairwise(altitudes):
        if upper - lower < 100.0:
            raise ValueError(
                f"Wind layers at {lower} ft and {upper} ft are within 100 ft of each other."
            )
    return layers


def _validate_cloud_layers(layers: list[CloudLayer]) -> list[CloudLayer]:
    if len(layers) > MAX_CLOUD_LAYERS:
        raise ValueError(f"At most {MAX_CLOUD_LAYERS} cloud layers, got {len(layers)}.")
    bases = [layer.base_ft for layer in layers]
    if bases != sorted(bases):
        raise ValueError("cloud_layers must be sorted ascending by base_ft.")
    for lower, upper in pairwise(bases):
        if upper - lower < 100.0:
            raise ValueError(
                f"Cloud layers based at {lower} ft and {upper} ft are within 100 ft of each other."
            )
    return layers


class WindLayer(BaseModel):
    """One wind stratum. Direction is where the wind blows FROM, true degrees."""

    model_config = ConfigDict(frozen=True)

    altitude_ft: float = Field(ge=0.0, description="Layer altitude, feet MSL.")
    direction_deg: float = Field(
        ge=0.0,
        le=360.0,
        description=(
            "Direction the wind blows FROM, TRUE degrees (METAR convention, and what "
            "the simulator's dataref expects). ATIS/tower winds are magnetic; "
            "converting for display is the UI's business, not this model's."
        ),
    )
    speed_kt: float = Field(ge=0.0, description="Sustained wind speed, knots.")
    gust_increase_kt: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Peak gust above the sustained speed, knots. 20 kt gusting 30 is "
            "speed_kt=20, gust_increase_kt=10."
        ),
    )
    turbulence_ratio: float = Field(
        default=0.0, ge=0.0, le=1.0, description="0 = smooth, 1 = severe."
    )


class CloudLayer(BaseModel):
    """One cloud stratum. Base below tops, both MSL."""

    model_config = ConfigDict(frozen=True)

    base_ft: float = Field(description="Cloud base, feet MSL.")
    tops_ft: float = Field(description="Cloud tops, feet MSL. Must exceed base_ft.")
    coverage_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Sky cover 0-1. Octas are display: FEW~=0.2, SCT~=0.44, BKN~=0.75, OVC=1.0.",
    )
    cloud_type: CloudType = Field(default="cumulus")

    @model_validator(mode="after")
    def _tops_above_base(self) -> CloudLayer:
        if self.tops_ft <= self.base_ft:
            raise ValueError(f"tops_ft ({self.tops_ft}) must exceed base_ft ({self.base_ft}).")
        return self


class WeatherState(BaseModel):
    """The commanded weather, fully populated — what ``get_weather()`` returns.

    Mirrors ``AircraftState``'s "always complete" convention rather than
    ``WeatherSetup``'s "None means untouched" one (weather-manager.md D4).
    ``dewpoint_c`` is clamped to ``temperature_c`` on construction rather than
    refused: a read describes what the simulator reports, and a state must
    always be representable (weather-manager.md §3.2).
    """

    model_config = ConfigDict(frozen=True)

    wind_layers: list[WindLayer] = Field(description="Ascending by altitude. May be empty (calm).")
    cloud_layers: list[CloudLayer] = Field(description="Ascending by base. May be empty (clear).")
    visibility_m: float = Field(
        ge=0.0,
        description=(
            "Surface visibility in METRES (CAT minima are metres; the adapter "
            "converts to the sim's unit)."
        ),
    )
    qnh_hpa: float = Field(ge=900.0, le=1100.0, description="Sea-level pressure, hectopascals.")
    temperature_c: float = Field(ge=-60.0, le=60.0, description="Sea-level temperature, Celsius.")
    dewpoint_c: float = Field(
        ge=-60.0,
        le=60.0,
        description=(
            "Sea-level dewpoint, Celsius. Never above temperature_c (clamped on "
            "construction). This is the feature spec's 'humidity' (D11)."
        ),
    )
    precipitation_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "0 = none, 1 = torrential. Falls as snow when the temperature says so — "
            "the phase is the simulator's decision, not a second field."
        ),
    )
    runway_contamination: RunwayContamination = Field(description="Surface state for friction.")

    @field_validator("wind_layers")
    @classmethod
    def _check_wind_layers(cls, layers: list[WindLayer]) -> list[WindLayer]:
        return _validate_wind_layers(layers)

    @field_validator("cloud_layers")
    @classmethod
    def _check_cloud_layers(cls, layers: list[CloudLayer]) -> list[CloudLayer]:
        return _validate_cloud_layers(layers)

    @model_validator(mode="before")
    @classmethod
    def _clamp_dewpoint_to_temperature(cls, data: object) -> object:
        if isinstance(data, dict):
            temperature = data.get("temperature_c")
            dewpoint = data.get("dewpoint_c")
            if (
                isinstance(temperature, int | float)
                and isinstance(dewpoint, int | float)
                and dewpoint > temperature
            ):
                data = {**data, "dewpoint_c": temperature}
        return data


class WeatherSetup(BaseModel):
    """The sparse write model. ``None`` means "leave that aspect untouched".

    Layer-list semantics (D3): ``None`` = untouched; a list REPLACES the whole
    set of layers; ``[]`` commands calm winds / clear skies. There is no
    per-layer merge. Unlike :class:`WeatherState`, a ``dewpoint_c`` above a
    stated ``temperature_c`` is refused rather than clamped — this is an
    instruction, and a self-contradictory one is a data-entry error.
    """

    model_config = ConfigDict(frozen=True)

    wind_layers: list[WindLayer] | None = None
    cloud_layers: list[CloudLayer] | None = None
    visibility_m: float | None = Field(default=None, ge=0.0)
    qnh_hpa: float | None = Field(default=None, ge=900.0, le=1100.0)
    temperature_c: float | None = Field(default=None, ge=-60.0, le=60.0)
    dewpoint_c: float | None = Field(default=None, ge=-60.0, le=60.0)
    precipitation_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    runway_contamination: RunwayContamination | None = None

    @field_validator("wind_layers")
    @classmethod
    def _check_wind_layers(cls, layers: list[WindLayer] | None) -> list[WindLayer] | None:
        return layers if layers is None else _validate_wind_layers(layers)

    @field_validator("cloud_layers")
    @classmethod
    def _check_cloud_layers(cls, layers: list[CloudLayer] | None) -> list[CloudLayer] | None:
        return layers if layers is None else _validate_cloud_layers(layers)

    @model_validator(mode="after")
    def _dewpoint_not_above_temperature(self) -> WeatherSetup:
        if (
            self.dewpoint_c is not None
            and self.temperature_c is not None
            and self.dewpoint_c > self.temperature_c
        ):
            raise ValueError(
                f"dewpoint_c ({self.dewpoint_c}) must not exceed temperature_c "
                f"({self.temperature_c})."
            )
        return self
