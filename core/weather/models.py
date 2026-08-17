"""The weather vocabulary: layers, the read model, the sparse write model.

Units are aviation-native and live in the field name (docs/designs/weather-manager.md
D13): ``_ft`` feet MSL, ``_kt`` knots, ``_deg`` TRUE degrees, ``_c`` Celsius,
``_hpa`` hectopascals, ``_m`` metres, ratios are dimensionless 0-1.

Layer-list semantics (D3, shared by :class:`WeatherState` and :class:`WeatherSetup`):
at most :data:`MAX_WIND_LAYERS` / :data:`MAX_CLOUD_LAYERS` entries, sorted
ascending by altitude/base, no two layers within 100 ft of each other — a
zero-thickness sandwich is a data error, not a weather.

The preset catalogue (``core/weather/presets.py::WEATHER_PRESETS``) and its
resolver are a separate track; the *models* a preset is built from —
``PresetWindLayer``, ``PresetCloudLayer``, ``WeatherPreset`` — and the request
model that both the REST layer and the (later) Scenario Generator share,
``WeatherRequest``, live here (weather-manager.md D6): the request model is
``core/`` vocabulary, never something stranded in ``server/`` (the Position
Manager's recorded regret, weather-manager.md §3.4).
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
    "PresetCloudLayer",
    "PresetWindLayer",
    "RunwayContamination",
    "WeatherPreset",
    "WeatherPresetId",
    "WeatherRequest",
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


class PresetWindLayer(BaseModel):
    """A preset's wind stratum: altitude AGL, direction absolute or runway-relative.

    Authored once per preset and resolved against a real airport/runway at
    apply time by ``core.weather.presets.resolve_preset`` — see
    weather-manager.md §3.3/§4 for why AGL and relative bearings live in the
    preset layer while ``WindLayer`` itself stays MSL/true.
    """

    model_config = ConfigDict(frozen=True)

    altitude_agl_ft: float = Field(ge=0.0, description="Above the chosen field's elevation.")
    direction_deg: float | None = Field(
        default=None,
        ge=0.0,
        le=360.0,
        description=(
            "TRUE degrees, absolute. Exactly one of this and offset_from_runway_deg "
            "is set (validator)."
        ),
    )
    offset_from_runway_deg: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Added to the runway's true bearing; +90 = wind from the right.",
    )
    speed_kt: float = Field(ge=0.0)
    gust_increase_kt: float = Field(default=0.0, ge=0.0)
    turbulence_ratio: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _exactly_one_direction_source(self) -> PresetWindLayer:
        if (self.direction_deg is None) == (self.offset_from_runway_deg is None):
            raise ValueError("Exactly one of direction_deg and offset_from_runway_deg must be set.")
        return self


class PresetCloudLayer(BaseModel):
    """A preset's cloud stratum, heights above the field."""

    model_config = ConfigDict(frozen=True)

    base_agl_ft: float = Field(ge=0.0, description="Cloud base, feet above the chosen field.")
    tops_agl_ft: float = Field(description="Cloud tops, feet AGL. Must exceed base_agl_ft.")
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    cloud_type: CloudType

    @model_validator(mode="after")
    def _tops_above_base(self) -> PresetCloudLayer:
        if self.tops_agl_ft <= self.base_agl_ft:
            raise ValueError(
                f"tops_agl_ft ({self.tops_agl_ft}) must exceed base_agl_ft ({self.base_agl_ft})."
            )
        return self


class WeatherPreset(BaseModel):
    """One named preset. Pure data — resolution is ``core.weather.presets.resolve_preset``.

    Presets are partial (weather-manager.md D2): a field left unset here is
    left untouched by the resolved setup, which is what makes ``cavok`` then
    ``crosswind`` compose into a clear day with a crosswind.
    """

    model_config = ConfigDict(frozen=True)

    id: WeatherPresetId
    label: str = Field(description='Display name, e.g. "CAT II".')
    description: str = Field(description="One sentence for the preset tile.")
    wind_layers: tuple[PresetWindLayer, ...] | None = None
    cloud_layers: tuple[PresetCloudLayer, ...] | None = None
    setup: WeatherSetup = WeatherSetup()

    @property
    def requires_runway(self) -> bool:
        """True when a wind layer's direction is stated relative to a runway."""
        if not self.wind_layers:
            return False
        return any(layer.offset_from_runway_deg is not None for layer in self.wind_layers)

    @property
    def requires_airport(self) -> bool:
        """True when the preset carries any AGL content (wind or cloud layers).

        Checked on actual content, not merely on the field being set: ``cavok``
        states ``cloud_layers=()`` (clear skies, resolved absolutely, no field
        elevation needed), and an empty tuple must not trip this the way a
        populated one does.
        """
        return bool(self.wind_layers) or bool(self.cloud_layers)


class WeatherRequest(BaseModel):
    """One weather instruction: a preset, an explicit setup, or a preset with overrides.

    Lives in ``core/`` (D6) so the Scenario Generator's YAML weather block
    validates against this exact model with no import from ``server/``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    # A typo'd field in a scenario YAML must fail loudly at load time — the
    # position models dropped this and regretted it.

    preset: WeatherPresetId | None = None
    airport_icao: str | None = Field(default=None, min_length=2, max_length=7)
    runway_ident: str | None = Field(default=None, min_length=1, max_length=3)
    setup: WeatherSetup | None = Field(
        default=None,
        description="The whole instruction when no preset is given, or the overlay over it.",
    )

    @model_validator(mode="after")
    def _preset_or_setup(self) -> WeatherRequest:
        if self.preset is None and self.setup is None:
            raise ValueError("A weather request must carry a preset, a setup, or both.")
        return self
