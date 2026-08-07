"""Shared vocabulary of the instructor station.

Every model here is simulator-agnostic. Units are part of the field name
(``_ft``, ``_kt``, ``_deg``, ``_kg``, ``_m``, ``_fpm``, ``_khz``) and are never
ambiguous: altitudes are MSL feet, headings/bearings are *true* degrees, speeds
are indicated knots unless stated otherwise.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AircraftSetup",
    "AircraftState",
    "GeoPosition",
    "Ils",
    "LightsSetup",
    "Runway",
    "RunwaySurface",
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


RunwaySurface = Literal[
    "asphalt",
    "concrete",
    "grass",
    "dirt",
    "gravel",
    "dry_lakebed",
    "water",
    "snow",
    "transparent",
    "unknown",
]


class Ils(BaseModel):
    """The ILS serving one runway end, ready to feed :class:`AircraftSetup`.

    Every field is in the unit and the reference frame the consumer needs, so
    tuning an approach is assignment and never arithmetic:
    :attr:`frequency_khz` goes straight into ``AircraftSetup.ils_freq_khz``,
    :attr:`localizer_mag_deg` into ``AircraftSetup.obs1_deg`` (an OBS course is
    **magnetic**), and :attr:`glideslope_deg` into
    ``core.geodesy.glideslope_altitude_ft``.

    **Both localizer bearings are carried because the source publishes both.**
    ``earth_nav.dat`` packs the true bearing and the magnetic front course into
    a single field, and neither is derivable from the other without a world
    magnetic model. The true one is what geometry is computed in; the magnetic
    one is what the aircraft's OBS and the approach plate are numbered in.

    This model lives here rather than in ``core/navdata/`` because
    :class:`Runway` carries one: putting it the other way round would make
    ``core/models.py`` and ``core/navdata/models.py`` import each other.
    """

    model_config = ConfigDict(frozen=True)

    airport_icao: str = Field(min_length=2, max_length=7, description='ICAO code, e.g. "LEMD".')
    runway_ident: str = Field(
        min_length=1, max_length=3, description='Runway served, e.g. "18L" — never "RW18L".'
    )
    localizer_ident: str = Field(description='Localizer identifier, e.g. "IML".')
    frequency_khz: int = Field(
        ge=108_000,
        le=111_950,
        description="Localizer frequency in kHz, the same unit as AircraftSetup.ils_freq_khz.",
    )
    localizer_position: GeoPosition = Field(description="Localizer antenna position.")
    localizer_true_deg: float = Field(
        ge=0.0, le=360.0, description="Localizer front course, TRUE degrees."
    )
    localizer_mag_deg: float = Field(
        ge=0.0,
        le=360.0,
        description=(
            "Localizer front course, MAGNETIC degrees — the published value, and what "
            "AircraftSetup.obs1_deg expects."
        ),
    )
    localizer_width_deg: float | None = Field(
        default=None, gt=0.0, description="Full course width in degrees, when published."
    )
    glideslope_deg: float | None = Field(
        default=None,
        gt=0.0,
        description="Glidepath angle in degrees, e.g. 3.00. None when the runway has no GS.",
    )
    glideslope_position: GeoPosition | None = Field(
        default=None, description="Glideslope antenna position, when the runway has one."
    )
    category: Literal["I", "II", "III"] | None = Field(
        default=None,
        description=(
            "ILS category. None when the source publishes nothing recognisable — an "
            "unexpected code is never allowed to fail a parse."
        ),
    )
    has_dme: bool = Field(default=False, description="True when a DME is collocated.")


class Runway(BaseModel):
    """A single runway end, as read from the user's own navdata.

    **A runway end has two distinct anchor points and they are not
    interchangeable.** The paved surface starts at the *pavement end*; the
    *landing threshold* is where an aircraft on final aims, and on a runway with
    a displaced threshold it sits some way down the pavement from that end. The
    two navdata sources this model is populated from disagree on which one they
    publish:

    * the CIFP ``RWY:`` record gives the **displaced landing threshold**;
    * ``apt.dat`` gives the **pavement end**, plus the displacement separately.

    At LEMD 18L those points are ~496 m apart — 0.27 NM of error on a 10 NM
    final if the two are conflated. So the convention is pinned here, once:

    * :attr:`threshold` is **always the displaced landing threshold**, and it is
      the origin every approach placement is measured from.
    * :attr:`pavement_end` is the other point, carried separately.
    * :attr:`length_m` is **always the pavement length**, because that is what
      traffic-pattern geometry is built on. Landing distance available is the
      separate :attr:`landing_distance_m`.

    A source that only knows the pavement end must walk it forward along the
    runway axis by :attr:`displaced_threshold_m` before filling
    :attr:`threshold` — it must never assign the pavement end to it.
    """

    model_config = ConfigDict(frozen=True)

    airport_icao: str = Field(min_length=2, max_length=7, description='ICAO code, e.g. "LEMD".')
    ident: str = Field(min_length=1, max_length=3, description='Runway identifier, e.g. "32L".')
    threshold: GeoPosition = Field(
        description=(
            "The displaced landing threshold — the point an aircraft on final aims at, NOT the "
            "start of the pavement (see pavement_end). This is the origin a final approach is "
            "measured back from."
        )
    )
    true_bearing_deg: float = Field(
        ge=0.0, le=360.0, description="Runway centreline bearing, true degrees."
    )
    length_m: float = Field(
        gt=0.0,
        description=(
            "Pavement length in metres, from one physical runway end to the other. This is the "
            "full paved length, NOT the landing distance available (see landing_distance_m)."
        ),
    )
    elevation_ft: float = Field(
        description="Elevation of the landing threshold, in feet above mean sea level."
    )

    # --- Optional, source-dependent detail --------------------------------
    # Every field below defaults, so a caller that only knows the six above
    # keeps working unchanged.
    pavement_end: GeoPosition | None = Field(
        default=None,
        description=(
            "Undisplaced start of the paved surface. Equal to the threshold when nothing is "
            "displaced; None when the source does not publish it."
        ),
    )
    displaced_threshold_m: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Distance in metres from pavement_end to threshold, along the runway centreline. "
            "0.0 means the threshold is not displaced. apt.dat publishes this in metres and the "
            "CIFP RWY: record publishes it in feet; both are converted to metres here."
        ),
    )
    landing_distance_m: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Landing distance available in metres, i.e. length_m minus displaced_threshold_m. "
            "None when the displacement is unknown."
        ),
    )
    opposite_ident: str | None = Field(
        default=None,
        min_length=1,
        max_length=3,
        description='The other end of the same strip, e.g. "36R" for "18L".',
    )
    width_m: float | None = Field(default=None, gt=0.0, description="Pavement width in metres.")
    surface: RunwaySurface | None = Field(
        default=None, description="Surface type, or None when the source does not publish one."
    )
    threshold_crossing_height_ft: float | None = Field(
        default=None,
        ge=0.0,
        description="Height of the glidepath over the threshold, in feet AGL, when published.",
    )
    ils: Ils | None = Field(
        default=None,
        description=(
            "The ILS serving this end, when there is one. Carried on the runway so that placing "
            "an aircraft on an ILS final is a single lookup: threshold, bearing, elevation, "
            "frequency and OBS course arrive together, and no caller can place an aircraft on an "
            "approach while forgetting to tune it."
        ),
    )
