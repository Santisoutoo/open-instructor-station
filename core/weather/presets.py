"""The preset catalogue and the pure resolver that turns one into a ``WeatherSetup``.

Presets are ``core/`` data (weather-manager.md D5): the seven the feature spec
names, authored once with AGL heights and runway-relative bearings so the same
catalogue entry means the right thing at every airport on Earth. Resolving a
preset — folding a runway's true bearing and a field's elevation into it — is a
pure function of plain numbers, never of a :class:`~core.navdata.provider.
NavdataProvider`: the caller (``server/weather_routes.py``) looks the numbers
up, this module never imports the provider.

Nothing here talks to a simulator or a navdata source. Everything is
unit-testable with hand-picked numbers, and everything the Scenario Generator
will need is importable from ``core/`` with no server-side detour (D6).
"""

from __future__ import annotations

from collections.abc import Mapping

from core.weather.models import (
    CloudLayer,
    PresetCloudLayer,
    PresetWindLayer,
    WeatherPreset,
    WeatherPresetId,
    WeatherRequest,
    WeatherSetup,
    WindLayer,
)

__all__ = [
    "WEATHER_PRESETS",
    "merge_setup",
    "resolve_preset",
    "resolve_request",
]


WEATHER_PRESETS: Mapping[WeatherPresetId, WeatherPreset] = {
    "cavok": WeatherPreset(
        id="cavok",
        label="CAVOK",
        description="Clear skies, unlimited visibility, ISA sea-level air. Wind is untouched.",
        cloud_layers=(),
        setup=WeatherSetup(
            visibility_m=20_000.0,
            qnh_hpa=1013.25,
            temperature_c=15.0,
            dewpoint_c=5.0,
            precipitation_ratio=0.0,
            runway_contamination="dry",
        ),
    ),
    "cat_i": WeatherPreset(
        id="cat_i",
        label="CAT I",
        description="Overcast stratus at the CAT I decision height, 800 m visibility.",
        cloud_layers=(
            PresetCloudLayer(
                base_agl_ft=250.0,
                tops_agl_ft=2_500.0,
                coverage_ratio=1.0,
                cloud_type="stratus",
            ),
        ),
        setup=WeatherSetup(
            visibility_m=800.0,
            temperature_c=12.0,
            dewpoint_c=12.0,
            precipitation_ratio=0.2,
            runway_contamination="wet",
        ),
    ),
    "cat_ii": WeatherPreset(
        id="cat_ii",
        label="CAT II",
        description="Overcast stratus at the CAT II decision height, 350 m visibility.",
        cloud_layers=(
            PresetCloudLayer(
                base_agl_ft=120.0,
                tops_agl_ft=2_000.0,
                coverage_ratio=1.0,
                cloud_type="stratus",
            ),
        ),
        setup=WeatherSetup(
            visibility_m=350.0,
            temperature_c=10.0,
            dewpoint_c=10.0,
            precipitation_ratio=0.1,
            runway_contamination="wet",
        ),
    ),
    "cat_iii": WeatherPreset(
        id="cat_iii",
        label="CAT III",
        description=(
            "Overcast stratus at the CAT III decision height, 125 m visibility, calm wind — "
            "radiation fog does not survive a breeze."
        ),
        wind_layers=(PresetWindLayer(altitude_agl_ft=0.0, direction_deg=360.0, speed_kt=3.0),),
        cloud_layers=(
            PresetCloudLayer(
                base_agl_ft=50.0,
                tops_agl_ft=1_500.0,
                coverage_ratio=1.0,
                cloud_type="stratus",
            ),
        ),
        setup=WeatherSetup(
            visibility_m=125.0,
            temperature_c=8.0,
            dewpoint_c=8.0,
            precipitation_ratio=0.0,
            runway_contamination="wet",
        ),
    ),
    "storm": WeatherPreset(
        id="storm",
        label="Storm",
        description="Severe convective weather: gusting wind, cumulonimbus, heavy rain.",
        wind_layers=(
            PresetWindLayer(
                altitude_agl_ft=0.0,
                direction_deg=240.0,
                speed_kt=25.0,
                gust_increase_kt=15.0,
                turbulence_ratio=0.7,
            ),
        ),
        cloud_layers=(
            PresetCloudLayer(
                base_agl_ft=4_000.0,
                tops_agl_ft=35_000.0,
                coverage_ratio=0.75,
                cloud_type="cumulonimbus",
            ),
        ),
        setup=WeatherSetup(
            visibility_m=3_000.0,
            qnh_hpa=998.0,
            temperature_c=22.0,
            dewpoint_c=20.0,
            precipitation_ratio=1.0,
            runway_contamination="puddles",
        ),
    ),
    "crosswind": WeatherPreset(
        id="crosswind",
        label="Crosswind",
        description=(
            "20 kt gusting 25, 90° off the active runway. States wind and nothing else, so it "
            "composes with any other preset applied first."
        ),
        wind_layers=(
            PresetWindLayer(
                altitude_agl_ft=0.0,
                offset_from_runway_deg=90.0,
                speed_kt=20.0,
                gust_increase_kt=5.0,
                turbulence_ratio=0.2,
            ),
        ),
    ),
    "mountain_wave": WeatherPreset(
        id="mountain_wave",
        label="Mountain Wave",
        description=(
            "Wind from 270°, strengthening and roughening with altitude. Absolute, not "
            "runway-relative: the station has no ridge-line data."
        ),
        wind_layers=(
            PresetWindLayer(altitude_agl_ft=0.0, direction_deg=270.0, speed_kt=15.0),
            PresetWindLayer(
                altitude_agl_ft=8_000.0,
                direction_deg=270.0,
                speed_kt=35.0,
                turbulence_ratio=0.3,
            ),
            PresetWindLayer(
                altitude_agl_ft=24_000.0,
                direction_deg=270.0,
                speed_kt=65.0,
                turbulence_ratio=0.6,
            ),
        ),
    ),
}


def _agl_content_label(preset: WeatherPreset) -> str:
    """What kind of AGL content a preset carries, for the "give airport_icao" refusal."""
    parts = []
    if preset.wind_layers:
        parts.append("wind altitudes")
    if preset.cloud_layers:
        parts.append("cloud heights")
    return " and ".join(parts) if parts else "altitudes"


def _resolve_wind_layers(
    layers: tuple[PresetWindLayer, ...],
    runway_true_bearing_deg: float,
    field_elevation_ft: float,
) -> tuple[list[WindLayer], list[str]]:
    resolved: list[WindLayer] = []
    notes: list[str] = []
    for layer in layers:
        if layer.direction_deg is not None:
            direction_deg = layer.direction_deg
        else:
            assert layer.offset_from_runway_deg is not None  # PresetWindLayer's own validator
            offset = layer.offset_from_runway_deg
            direction_deg = (runway_true_bearing_deg + offset) % 360.0
            gust = (
                f" gusting {layer.speed_kt + layer.gust_increase_kt:g}"
                if layer.gust_increase_kt
                else ""
            )
            side = "right" if offset >= 0.0 else "left"
            notes.append(
                f"Wind {direction_deg:03.0f}° at {layer.speed_kt:g} kt{gust} — "
                f"{abs(offset):g}° {side} of the runway's true bearing of "
                f"{runway_true_bearing_deg:03.0f}°."
            )
        resolved.append(
            WindLayer(
                altitude_ft=field_elevation_ft + layer.altitude_agl_ft,
                direction_deg=direction_deg,
                speed_kt=layer.speed_kt,
                gust_increase_kt=layer.gust_increase_kt,
                turbulence_ratio=layer.turbulence_ratio,
            )
        )
    return resolved, notes


def _resolve_cloud_layers(
    layers: tuple[PresetCloudLayer, ...],
    field_elevation_ft: float,
) -> tuple[list[CloudLayer], list[str]]:
    resolved: list[CloudLayer] = []
    notes: list[str] = []
    for layer in layers:
        base_ft = field_elevation_ft + layer.base_agl_ft
        tops_ft = field_elevation_ft + layer.tops_agl_ft
        resolved.append(
            CloudLayer(
                base_ft=base_ft,
                tops_ft=tops_ft,
                coverage_ratio=layer.coverage_ratio,
                cloud_type=layer.cloud_type,
            )
        )
        notes.append(
            f"Cloud base {base_ft:,.0f} ft MSL — {layer.base_agl_ft:,.0f} ft above the field's "
            f"elevation of {field_elevation_ft:,.0f} ft."
        )
    return resolved, notes


def resolve_preset(
    preset: WeatherPreset,
    *,
    runway_true_bearing_deg: float | None = None,
    field_elevation_ft: float | None = None,
) -> tuple[WeatherSetup, tuple[str, ...]]:
    """Resolve a preset's relative parts into an absolute ``WeatherSetup``, with notes.

    Pure: ``(preset, bearing, elevation)`` in, ``(setup, notes)`` out. The
    caller looks ``runway_true_bearing_deg``/``field_elevation_ft`` up in
    navdata; this function never sees the provider (weather-manager.md D5).

    Raises:
        ValueError: the preset needs context it was not given —
            ``requires_runway`` and no bearing, or ``requires_airport`` and no
            elevation.
    """
    if preset.requires_runway and runway_true_bearing_deg is None:
        raise ValueError(
            f"The {preset.id!r} preset is relative to a runway; give airport_icao and runway_ident."
        )
    if preset.requires_airport and field_elevation_ft is None:
        raise ValueError(
            f"The {preset.id!r} preset states {_agl_content_label(preset)} above the field; "
            f"give airport_icao."
        )

    updates: dict[str, object] = {}
    notes: list[str] = []

    # ``is not None`` decides whether the field is STATED (D3: an empty tuple
    # is a meaningful "clear/calm" command, same as WeatherSetup's own
    # semantics); truthiness decides whether there is a LAYER to convert.
    # cavok states cloud_layers=() and needs no field_elevation_ft at all —
    # requires_airport is False for it precisely because the tuple is empty,
    # so the elevation is only ever dereferenced once a layer actually exists,
    # which is exactly what requires_airport having gated above guarantees.
    if preset.wind_layers is not None:
        if preset.wind_layers:
            assert field_elevation_ft is not None  # requires_airport gate above
            wind_layers, wind_notes = _resolve_wind_layers(
                preset.wind_layers,
                # requires_runway gate above guarantees this when any layer needs it.
                runway_true_bearing_deg if runway_true_bearing_deg is not None else 0.0,
                field_elevation_ft,
            )
        else:
            wind_layers, wind_notes = [], []
        updates["wind_layers"] = wind_layers
        notes.extend(wind_notes)

    if preset.cloud_layers is not None:
        if preset.cloud_layers:
            assert field_elevation_ft is not None  # requires_airport gate above
            cloud_layers, cloud_notes = _resolve_cloud_layers(
                preset.cloud_layers, field_elevation_ft
            )
        else:
            cloud_layers, cloud_notes = [], []
        updates["cloud_layers"] = cloud_layers
        notes.extend(cloud_notes)

    merged = {**preset.setup.model_dump(), **updates}
    resolved = WeatherSetup.model_validate(merged)
    return resolved, tuple(notes)


def merge_setup(base: WeatherSetup, overlay: WeatherSetup) -> WeatherSetup:
    """Overlay the set fields of ``overlay`` onto ``base`` and RE-VALIDATE.

    ``model_validate`` on the merged dump, not ``model_copy(update=...)`` — the
    position router's merge bug (a nested dict surviving un-validated to the
    adapter) is a lesson, not a tradition. Layer lists follow D3: an overlay
    list replaces the base list wholesale.
    """
    merged = {**base.model_dump(), **overlay.model_dump(exclude_none=True)}
    return WeatherSetup.model_validate(merged)


def _override_notes(
    preset_id: WeatherPresetId, base: WeatherSetup, overlay: WeatherSetup
) -> list[str]:
    """One provenance sentence per field the overlay displaced, naming the preset's own value."""
    base_dump = base.model_dump()
    overlay_fields = overlay.model_dump(exclude_none=True)
    notes: list[str] = []
    for field in sorted(overlay_fields):
        new_value = overlay_fields[field]
        old_value = base_dump.get(field)
        if old_value is None:
            notes.append(
                f"{field}={new_value!r} — your override; the {preset_id!r} preset left it "
                f"untouched."
            )
        else:
            notes.append(
                f"{field}={new_value!r} — your override; the {preset_id!r} preset states "
                f"{old_value!r}."
            )
    return notes


def resolve_request(
    request: WeatherRequest,
    *,
    runway_true_bearing_deg: float | None = None,
    field_elevation_ft: float | None = None,
) -> tuple[WeatherSetup, tuple[str, ...]]:
    """The one entry point ``preview``, ``apply`` and (later) the scenario engine share.

    Resolves the preset if any, merges ``request.setup`` over it (D7: a client
    can never hand the server a pre-resolved preset), and notes the provenance
    of every resolved number and every override that displaced a preset value.
    """
    if request.preset is None:
        assert request.setup is not None  # WeatherRequest's own validator
        return request.setup, ()

    preset = WEATHER_PRESETS[request.preset]
    resolved, preset_notes = resolve_preset(
        preset,
        runway_true_bearing_deg=runway_true_bearing_deg,
        field_elevation_ft=field_elevation_ft,
    )
    notes = list(preset_notes)
    if request.setup is not None:
        notes.extend(_override_notes(request.preset, resolved, request.setup))
        resolved = merge_setup(resolved, request.setup)
    return resolved, tuple(notes)
