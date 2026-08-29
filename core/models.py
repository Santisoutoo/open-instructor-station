"""Shared vocabulary of the instructor station.

Every model here is simulator-agnostic. Units are part of the field name
(``_ft``, ``_kt``, ``_deg``, ``_kg``, ``_m``, ``_fpm``, ``_khz``) and are never
ambiguous: altitudes are MSL feet, headings/bearings are *true* degrees, speeds
are indicated knots unless stated otherwise.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "MAX_FUEL_TANKS",
    "MAX_PAYLOAD_STATIONS",
    "AircraftSetup",
    "AircraftState",
    "AirframeInfo",
    "AirframeMassLimits",
    "CgEnvelope",
    "CgEnvelopePoint",
    "GeoPosition",
    "Ils",
    "LightsSetup",
    "Loadout",
    "LoadoutState",
    "PayloadStation",
    "Runway",
    "RunwaySurface",
    "StationKind",
    "TankFuel",
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


MAX_FUEL_TANKS = 8
MAX_PAYLOAD_STATIONS = 12


class TankFuel(BaseModel):
    """Fuel in one tank."""

    model_config = ConfigDict(frozen=True)

    tank_index: int = Field(
        ge=0,
        lt=MAX_FUEL_TANKS,
        description="0-based tank index, in the order get_loadout() reports — adapter-defined.",
    )
    fuel_kg: float = Field(ge=0.0, description="Fuel mass in this tank, kilograms.")


StationKind = Literal["crew", "passenger", "cargo", "other"]


class PayloadStation(BaseModel):
    """Mass at one payload station.

    The simulator itself does not distinguish what a station is FOR — X-Plane's
    ``m_stations`` array and MSFS's payload stations are both bare masses at
    bare positions. ``kind`` is an instructor-facing label, assigned here or by
    a future per-aircraft mapping table, never invented from the mass alone.
    """

    model_config = ConfigDict(frozen=True)

    station_index: int = Field(ge=0, lt=MAX_PAYLOAD_STATIONS, description="0-based, adapter order.")
    kind: StationKind = Field(default="other", description="Instructor-facing classification.")
    label: str = Field(default="", description='Display label, e.g. "Pilot". Blank when unknown.')
    weight_kg: float = Field(ge=0.0, description="Mass placed at this station, kilograms.")


class Loadout(BaseModel):
    """Fuel and payload — the sparse write model nested on :class:`AircraftSetup`.

    ``None`` means "leave that aspect untouched"; a provided list REPLACES the
    whole set of tanks/stations, ``[]`` empties every one — the Weather
    Manager's wind/cloud-layer semantics (``docs/designs/weather-manager.md``
    D3), for the identical reason: there is no defensible per-index merge.
    """

    tanks: list[TankFuel] | None = None
    stations: list[PayloadStation] | None = None


class LoadoutState(BaseModel):
    """Fully populated fuel and payload, as reported by ``get_loadout()``.

    Every known tank/station is present — mirrors :class:`AircraftState`'s
    "always complete" convention rather than :class:`AircraftSetup`'s "None
    means untouched" one (the same ``WeatherState``/``WeatherSetup`` split).
    """

    tanks: list[TankFuel] = Field(description="Every known tank, in adapter order. [] if none.")
    stations: list[PayloadStation] = Field(
        description="Every known station, in adapter order. [] if none."
    )


class CgEnvelopePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    weight_kg: float = Field(ge=0.0)
    fwd_limit_in: float = Field(description="Forward CG limit at this weight, inches aft of datum.")
    aft_limit_in: float = Field(description="Aft CG limit at this weight. >= fwd_limit_in.")

    @model_validator(mode="after")
    def _aft_not_forward_of_fwd(self) -> CgEnvelopePoint:
        if self.aft_limit_in < self.fwd_limit_in:
            raise ValueError(
                f"aft_limit_in ({self.aft_limit_in}) must be >= fwd_limit_in ({self.fwd_limit_in})."
            )
        return self


class CgEnvelope(BaseModel):
    """A weight-vs-CG-limit polygon, linearly interpolated between points."""

    model_config = ConfigDict(frozen=True)

    points: tuple[CgEnvelopePoint, ...] = Field(
        min_length=2,
        description="Ascending by weight_kg. Outside the range is a validation failure — no "
        "straight-line extrapolation past a published envelope.",
    )

    @model_validator(mode="after")
    def _points_ascend_by_weight(self) -> CgEnvelope:
        weights = [point.weight_kg for point in self.points]
        if weights != sorted(weights):
            raise ValueError("cg_envelope.points must be sorted ascending by weight_kg.")
        return self


class AirframeMassLimits(BaseModel):
    """Static mass-and-balance facts about the loaded airframe.

    All-or-nothing: an adapter that cannot supply the complete set reports
    ``None`` on :attr:`AirframeInfo.mass_limits` rather than a half-populated
    model.
    """

    model_config = ConfigDict(frozen=True)

    empty_weight_kg: float = Field(gt=0.0)
    empty_cg_arm_in: float
    max_takeoff_weight_kg: float = Field(gt=0.0)
    max_zero_fuel_weight_kg: float | None = Field(default=None, gt=0.0)
    max_fuel_kg: float = Field(gt=0.0)
    fuel_tank_capacities_kg: tuple[float, ...] = Field(min_length=1)
    fuel_tank_arms_in: tuple[float, ...] = Field(
        min_length=1, description="Same order/length as capacities."
    )
    payload_station_capacities_kg: tuple[float, ...] = Field(min_length=1)
    payload_station_arms_in: tuple[float, ...] = Field(min_length=1)
    cg_envelope: CgEnvelope

    @model_validator(mode="after")
    def _capacities_and_arms_match(self) -> AirframeMassLimits:
        if len(self.fuel_tank_capacities_kg) != len(self.fuel_tank_arms_in):
            raise ValueError(
                "fuel_tank_capacities_kg and fuel_tank_arms_in must be the same length."
            )
        if len(self.payload_station_capacities_kg) != len(self.payload_station_arms_in):
            raise ValueError(
                "payload_station_capacities_kg and payload_station_arms_in must be the same length."
            )
        return self


class AirframeInfo(BaseModel):
    """What is known about the loaded airframe. Every field degrades to ``None``.

    A read, not a command: :meth:`core.sim_adapter.SimAdapter.get_airframe`
    returns one of these, and an adapter that cannot see the airframe returns
    the all-``None`` model rather than raising — "unknown" is an honest answer
    and never an error (the same posture as every other capability-free read).

    The consumer is the approach-category derivation (issue #82): a stall speed
    turns into V_AT and V_AT into an ICAO approach category in ``core/``, which
    never talks to a simulator itself — the airframe arrives as an input.
    """

    model_config = ConfigDict(frozen=True)

    icao_type: str | None = Field(
        default=None, description='ICAO type designator of the loaded aircraft, e.g. "C172".'
    )
    vso_kias: float | None = Field(
        default=None,
        gt=0.0,
        description="Stall speed in the landing configuration, knots indicated.",
    )
    mass_limits: AirframeMassLimits | None = Field(
        default=None,
        description="None when neither the simulator nor the core/ fallback table knows this "
        "airframe's mass-and-balance facts — 'unknown' is an honest answer, never invented data.",
    )


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

    **This model is the whole write surface of the aircraft**, autopilot
    included. There is deliberately no separate ``set_autopilot`` seam on
    :class:`~core.sim_adapter.SimAdapter`: an instructor arming HDG and dialling
    the heading bug is one intent, and splitting it across two calls would make
    it two half-applied states an aircraft can be caught between. The fields are
    still gated separately — the autopilot block needs
    :attr:`~core.sim_adapter.Capabilities.can_control_autopilot`, everything else
    needs ``can_set_aircraft_state`` — so an adapter that cannot drive an
    autopilot refuses those fields and honours the rest.
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
    loadout: Loadout | None = Field(
        default=None,
        description="Per-tank fuel and per-station payload. Requires can_set_fuel_payload, "
        "the same flag as gross_weight_kg/fuel_kg. When both are set, loadout is authoritative.",
    )

    # --- Configuration ----------------------------------------------------
    flaps_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0, description="0 = up, 1 = fully deployed."
    )
    speedbrake_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0, description="0 = retracted, 1 = fully deployed."
    )
    elevator_trim_ratio: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="-1 = full nose down, 0 = neutral, +1 = full nose up.",
    )
    throttle_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "0 = idle, 1 = full thrust, fanned out to every engine. Commanded at "
            "placement, not held: an aircraft whose own systems move the levers "
            "afterwards is expected behaviour."
        ),
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

    # --- Autopilot --------------------------------------------------------
    # Requires Capabilities.can_control_autopilot. Two conventions are pinned
    # here because getting either wrong is silent:
    #
    # * The mode flags are *selections*, not a description of what the aircraft
    #   is doing. Arming NAV does not make the aircraft turn — the servos do,
    #   and those are `autopilot_master`.
    # * `target_heading_deg` is MAGNETIC, unlike every other heading in this
    #   module. A heading bug is magnetic on the real aeroplane and in every
    #   simulator that models one, the same way `obs1_deg` is.
    autopilot_master: bool | None = Field(
        default=None, description="True = autopilot servos engaged and flying the aircraft."
    )
    flight_director: bool | None = Field(
        default=None,
        description=(
            "True = flight director bars shown. Engaging the autopilot implies a flight "
            "director; switching the flight director off switches the autopilot off with it."
        ),
    )
    autopilot_nav: bool | None = Field(
        default=None, description="True = NAV (VOR/LOC/GPS) selected as the lateral mode."
    )
    autopilot_app: bool | None = Field(
        default=None, description="True = APPROACH selected as the lateral mode."
    )
    autopilot_hdg: bool | None = Field(
        default=None, description="True = HEADING selected as the lateral mode."
    )
    target_altitude_ft: float | None = Field(
        default=None, description="Autopilot altitude selector, feet MSL. Not the aircraft's."
    )
    target_ias_kt: float | None = Field(
        default=None, ge=0.0, description="Autopilot speed selector, indicated knots."
    )
    target_heading_deg: float | None = Field(
        default=None,
        ge=0.0,
        le=360.0,
        description="Autopilot heading bug, MAGNETIC degrees (a heading selector always is).",
    )
    target_vertical_speed_fpm: float | None = Field(
        default=None, description="Autopilot vertical speed selector, feet per minute."
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
