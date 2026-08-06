"""Shared vocabulary of the instructor station.

Every model here is simulator-agnostic. Units are part of the field name
(``_ft``, ``_kt``, ``_deg``, ``_kg``, ``_m``, ``_fpm``, ``_khz``) and are never
ambiguous: altitudes are MSL feet, headings/bearings are *true* degrees, speeds
are indicated knots unless stated otherwise.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AircraftSetup",
    "AircraftState",
    "GeoPosition",
    "LightsSetup",
    "Runway",
]


class GeoPosition(BaseModel):
    """A point on the WGS84 ellipsoid with an MSL altitude."""

    model_config = ConfigDict(frozen=True)

    latitude: float = Field(ge=-90.0, le=90.0, description="Degrees, WGS84, positive north.")
    longitude: float = Field(ge=-180.0, le=180.0, description="Degrees, WGS84, positive east.")
    altitude_ft: float = Field(default=0.0, description="Feet above mean sea level.")


class AircraftState(BaseModel):
    """A live snapshot of the user aircraft, as streamed over the WebSocket."""

    latitude: float = Field(ge=-90.0, le=90.0, description="Degrees, WGS84, positive north.")
    longitude: float = Field(ge=-180.0, le=180.0, description="Degrees, WGS84, positive east.")
    altitude_ft: float = Field(description="Feet above mean sea level.")
    heading_deg: float = Field(ge=0.0, le=360.0, description="True heading in degrees.")
    ias_kt: float = Field(ge=0.0, description="Indicated airspeed in knots.")
    vertical_speed_fpm: float = Field(description="Vertical speed in feet per minute.")
    pitch_deg: float = Field(ge=-90.0, le=90.0, description="Pitch in degrees, positive nose up.")
    roll_deg: float = Field(
        ge=-180.0, le=180.0, description="Bank in degrees, positive right wing down."
    )
    on_ground: bool = Field(default=False, description="True when any gear touches the ground.")


class LightsSetup(BaseModel):
    """Exterior light switches. ``None`` means "leave this switch untouched"."""

    landing: bool | None = None
    taxi: bool | None = None
    nav: bool | None = None
    beacon: bool | None = None
    strobe: bool | None = None


class AircraftSetup(BaseModel):
    """The "configure before teleport" payload.

    Every field is optional: ``None`` means *leave that aspect of the aircraft
    untouched*. An adapter must apply exactly the fields that are set and must
    not reset the others to a default.
    """

    # --- Flight state -----------------------------------------------------
    altitude_ft: float | None = Field(default=None, description="Feet above mean sea level.")
    ias_kt: float | None = Field(default=None, ge=0.0, description="Indicated airspeed in knots.")
    vertical_speed_fpm: float | None = Field(default=None, description="Feet per minute.")
    heading_deg: float | None = Field(
        default=None, ge=0.0, le=360.0, description="True heading in degrees."
    )
    pitch_deg: float | None = Field(
        default=None, ge=-90.0, le=90.0, description="Degrees, positive nose up."
    )
    roll_deg: float | None = Field(
        default=None, ge=-180.0, le=180.0, description="Degrees, positive right wing down."
    )

    # --- Mass -------------------------------------------------------------
    gross_weight_kg: float | None = Field(
        default=None, ge=0.0, description="Total aircraft mass in kilograms."
    )
    fuel_kg: float | None = Field(default=None, ge=0.0, description="Total fuel in kilograms.")

    # --- Configuration ----------------------------------------------------
    flaps_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0, description="0 = up, 1 = fully deployed."
    )
    speedbrake_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0, description="0 = retracted, 1 = fully deployed."
    )
    gear_down: bool | None = Field(default=None, description="True = gear down and locked.")
    autobrake_level: int | None = Field(
        default=None, ge=0, le=5, description="0 = off, increasing = stronger deceleration."
    )
    lights: LightsSetup | None = Field(default=None, description="Exterior light switches.")

    # --- Radios -----------------------------------------------------------
    nav1_freq_khz: int | None = Field(
        default=None, ge=108_000, le=117_950, description="NAV1 frequency in kHz."
    )
    nav2_freq_khz: int | None = Field(
        default=None, ge=108_000, le=117_950, description="NAV2 frequency in kHz."
    )
    ils_freq_khz: int | None = Field(
        default=None, ge=108_000, le=111_950, description="ILS frequency in kHz."
    )
    obs1_deg: float | None = Field(
        default=None, ge=0.0, le=360.0, description="NAV1 OBS course in degrees."
    )
    obs2_deg: float | None = Field(
        default=None, ge=0.0, le=360.0, description="NAV2 OBS course in degrees."
    )


class Runway(BaseModel):
    """A single runway end, as read from the user's own navdata."""

    model_config = ConfigDict(frozen=True)

    airport_icao: str = Field(min_length=2, max_length=7, description='ICAO code, e.g. "LEMD".')
    ident: str = Field(min_length=1, max_length=3, description='Runway identifier, e.g. "32L".')
    threshold: GeoPosition = Field(description="Landing threshold position.")
    true_bearing_deg: float = Field(
        ge=0.0, le=360.0, description="Runway centreline bearing, true degrees."
    )
    length_m: float = Field(gt=0.0, description="Usable length in metres.")
    elevation_ft: float = Field(description="Threshold elevation in feet MSL.")
