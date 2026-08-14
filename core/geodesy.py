"""WGS84 geodesy primitives and the placements built on them.

Pure functions over :mod:`core.models` — no simulator, no I/O, no global state.
All distances taken and returned by the public API are **nautical miles**, all
bearings and headings are **true degrees** normalised to ``[0, 360)``, and all
altitudes are **feet MSL**. Internally everything runs through
:mod:`geographiclib` on the WGS84 ellipsoid, whose native unit is the metre.

The module has two layers:

**Primitives.** :func:`point_at_distance_and_bearing` and
:func:`distance_and_bearing` are the direct and inverse geodesic problems;
:func:`glideslope_altitude_ft`, :func:`final_approach_point` and
:func:`traffic_pattern_point` are the runway geometry built on them. They take
raw numbers and answer with raw numbers.

**Every runway-relative distance here is measured from the displaced landing
threshold.** :class:`~core.models.Runway` carries two anchor points that are not
interchangeable — ``threshold``, where an aircraft on final aims, and
``pavement_end``, where the paving starts — and everything in this module uses
``threshold``. ``length_m`` is the *pavement* length, which is what the
traffic-pattern geometry is built on. At LEMD 18L the two anchors are ~496 m
apart, so a function here that quietly took the pavement end would displace
every final by 0.27 NM while the geometry still looked flawless. The convention
is stated in full on :class:`~core.models.Runway`; this module assumes it.

**Placements.** Every runway-relative position the Position Manager offers has a
name — ``"final_10nm"``, ``"left_downwind"``, ``"short_final"`` — and resolving
one yields a :class:`Placement`: *where* to put the aircraft, at *what*
altitude, pointing *which* way and at *what speed*. :data:`RUNWAY_PLACEMENTS` is
the whole catalogue and :func:`resolve_runway_placement` is the single entry
point, so an API layer enumerates and dispatches without knowing any geometry.
:func:`coordinate_placement` and :func:`waypoint_placement` cover the two
placements that need no runway.

**Placements driven by published navdata.** A holding pattern and a procedure
leg are not geometry an instructor station gets to invent: the fix, the inbound
course, the turn direction, the leg length, the altitude and the speed are all
*published*, and the only honest thing to do with them is read them.
:func:`hold_placement`, :func:`hold_entry_placement` and
:func:`procedure_leg_placement` therefore take the models
:mod:`core.navdata.models` already publishes — :class:`~core.navdata.models.Hold`
and :class:`~core.navdata.models.ProcedureLeg` — and compute only what the
source genuinely leaves open: where the racetrack lies on the ground, and which
entry an arriving aircraft would fly. Importing those models is safe in this
direction and only in this direction: they depend on :mod:`core.models` alone,
while :mod:`core.navdata` depends on this module.

**Published courses are magnetic and this module is true.** ``earth_hold.dat``
and the CIFP publish courses in magnetic degrees; every bearing here is true.
Converting needs a world magnetic model, which this project deliberately does
not carry, so the conversion is the caller's — :func:`true_from_magnetic` is
where it happens, and every function that consumes a magnetic course takes
``magnetic_variation_deg`` as a **required** argument. Defaulting it to zero
would silently rotate a whole holding pattern by the local variation, which is
13° at KJFK.

**A placement commands its own speed.** Carrying the aircraft's *current* speed
onto the new position is the right rule for moving an aeroplane that is already
flying and the wrong one for a placement: a parked aircraft put on a 10 NM final
arrives at 0 kt and falls out of the sky. That was measured, not theorised — the
geometry was perfect (0.2 m from the target, 10.000 NM out, on the extended
centreline) and the aircraft still flew into terrain, simply below stall speed.
So :class:`Placement` carries a **required** ``ias_kt``: a placement cannot be
built without someone deciding how fast the aircraft is meant to be going.

The default comes from the aircraft's **ICAO approach category**
(:data:`ApproachCategory`) rather than from a single number, because a C172 and
a 737 do not fly the same final. See :data:`APPROACH_CATEGORY_VAT_KT` for what
the defaults are worth and where they stop being trustworthy.

"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Literal, assert_never

from geographiclib.geodesic import Geodesic
from pydantic import BaseModel, ConfigDict, Field

from core.atmosphere import tas_from_ias
from core.models import AircraftSetup, GeoPosition, Ils, LightsSetup, Runway
from core.navdata.models import Hold, Procedure, ProcedureLeg, Waypoint

__all__ = [
    "APPROACH_CATEGORY_CIRCLING_IAS_KT",
    "APPROACH_CATEGORY_VAT_KT",
    "BASE_FLAPS_RATIO",
    "CIRCUIT_THROTTLE",
    "CRUISE_THROTTLE",
    "DEFAULT_APPROACH_CATEGORY",
    "DEFAULT_GLIDESLOPE_DEG",
    "DEFAULT_HOLD_ENTRY_DISTANCE_NM",
    "DEFAULT_PATTERN_ALTITUDE_AGL_FT",
    "DEFAULT_PATTERN_LEG_DISTANCE_NM",
    "DEFAULT_PATTERN_WIDTH_NM",
    "FEET_PER_MINUTE_PER_KNOT",
    "FEET_PER_NAUTICAL_MILE",
    "FINAL_DISTANCES_NM",
    "FINAL_FLAPS_RATIO",
    "FINAL_THROTTLE",
    "FINAL_TRIM",
    "GROUND_IAS_KT",
    "HOLD_LEG_TIME_ALTITUDE_FT",
    "HOLD_LEG_TIME_HIGH_MIN",
    "HOLD_LEG_TIME_LOW_MIN",
    "HOLD_MAX_BANK_DEG",
    "HOLD_PLACEMENTS",
    "HOLD_RATE_OF_TURN_DEG_PER_S",
    "METRES_PER_NAUTICAL_MILE",
    "PARALLEL_ENTRY_SECTOR_DEG",
    "PATTERN_PLACEMENTS",
    "RUNWAY_PLACEMENTS",
    "SHORT_FINAL_DISTANCE_NM",
    "TEARDROP_ENTRY_SECTOR_DEG",
    "VAT_FROM_VSO",
    "ApproachCategory",
    "FinalPlacement",
    "HoldEntry",
    "HoldPlacement",
    "PatternLeg",
    "PatternPlacement",
    "PatternSide",
    "Placement",
    "PlacementProfile",
    "RunwayPlacement",
    "TurnDirection",
    "category_for_vat",
    "coordinate_placement",
    "distance_and_bearing",
    "final_approach_point",
    "final_placement",
    "glideslope_altitude_ft",
    "hold_entry",
    "hold_entry_placement",
    "hold_leg_length_nm",
    "hold_placement",
    "holding_entry",
    "holding_pattern_point",
    "pattern_placement",
    "point_at_distance_and_bearing",
    "positionable_legs",
    "procedure_leg_placement",
    "procedure_placement",
    "resolve_runway_placement",
    "traffic_pattern_point",
    "true_from_magnetic",
    "turn_radius_nm",
    "waypoint_placement",
]

#: Exact conversion: 1 international nautical mile = 1852 m = 1852 / 0.3048 ft.
METRES_PER_NAUTICAL_MILE: float = 1852.0
FEET_PER_NAUTICAL_MILE: float = METRES_PER_NAUTICAL_MILE / 0.3048  # 6076.115485564304

#: Legs of a standard rectangular traffic pattern.
PatternLeg = Literal["downwind", "base", "crosswind", "upwind"]

#: Which side of the runway the pattern is flown on.
PatternSide = Literal["left", "right"]

#: What kind of flying a placement puts the aircraft into. The profile decides
#: the configuration :meth:`Placement.to_setup` emits — gear, flaps, throttle,
#: trim, descent — because a short final is not configured like a hold, and
#: speed alone is not a stabilised approach (issue #8).
PlacementProfile = Literal["final", "circuit", "airborne", "ground"]

#: The finals the Position Manager offers, named after their distance out.
FinalPlacement = Literal[
    "final_20nm",
    "final_15nm",
    "final_10nm",
    "final_8nm",
    "final_5nm",
    "final_3nm",
    "short_final",
]

#: The eight circuit positions: four legs, left-hand and right-hand.
PatternPlacement = Literal[
    "left_upwind",
    "left_crosswind",
    "left_downwind",
    "left_base",
    "right_upwind",
    "right_crosswind",
    "right_downwind",
    "right_base",
]

#: Every placement that is defined relative to a runway.
RunwayPlacement = FinalPlacement | PatternPlacement

#: Which way an aircraft turns in a pattern. Spelled exactly as the navdata
#: publishes it, so :attr:`core.navdata.models.Hold.turn_direction` and
#: :attr:`core.navdata.models.ProcedureLeg.turn_direction` pass straight in.
TurnDirection = Literal["L", "R"]

#: The three ICAO holding entries.
HoldEntry = Literal["direct", "parallel", "teardrop"]

#: The four points of a holding pattern an aircraft can be placed at, going
#: round the racetrack in the order they are flown from the fix.
HoldPlacement = Literal["hold_fix", "hold_outbound", "hold_outbound_end", "hold_inbound"]

#: The hold placements, in menu order.
HOLD_PLACEMENTS: tuple[HoldPlacement, ...] = (
    "hold_fix",
    "hold_outbound",
    "hold_outbound_end",
    "hold_inbound",
)

#: How each hold placement reads in a menu.
_HOLD_PLACEMENT_LABELS: Mapping[HoldPlacement, str] = MappingProxyType(
    {
        "hold_fix": "over the fix",
        "hold_outbound": "outbound abeam the fix",
        "hold_outbound_end": "end of the outbound leg",
        "hold_inbound": "established inbound",
    }
)

#: ICAO standard glidepath angle, degrees.
DEFAULT_GLIDESLOPE_DEG: float = 3.0

#: "Short final" is the last mile: inside 1 NM the aircraft is committed,
#: configured and — on a 3° path — about 318 ft above threshold elevation.
SHORT_FINAL_DISTANCE_NM: float = 1.0

#: Height above the runway a standard circuit is flown at, feet AGL. Used when
#: the caller does not state a pattern altitude.
DEFAULT_PATTERN_ALTITUDE_AGL_FT: float = 1000.0

#: Lateral distance from the centreline to the downwind leg, nautical miles.
DEFAULT_PATTERN_WIDTH_NM: float = 1.0

#: How far beyond the departure end the upwind/crosswind legs sit, and how far
#: before the threshold the base leg sits, nautical miles.
DEFAULT_PATTERN_LEG_DISTANCE_NM: float = 1.5

#: ICAO Doc 8168 turn criterion for holding: 25° of bank, or a rate of 3° per
#: second, **whichever requires the lesser bank**. The two cross at about
#: 170 kt true: below it the rate is the binding constraint, above it the bank
#: is. "Lesser bank" is the same statement as "larger radius", which is how
#: :func:`turn_radius_nm` applies it.
HOLD_RATE_OF_TURN_DEG_PER_S: float = 3.0
HOLD_MAX_BANK_DEG: float = 25.0

#: Standard holding leg times, minutes, and the altitude that selects between
#: them: one minute at or below 14 000 ft, one and a half above it. Used only
#: when the published hold states neither a leg time nor a leg length.
HOLD_LEG_TIME_LOW_MIN: float = 1.0
HOLD_LEG_TIME_HIGH_MIN: float = 1.5
HOLD_LEG_TIME_ALTITUDE_FT: float = 14_000.0

#: Width of the parallel-entry sector, degrees, measured from the reciprocal of
#: the inbound course towards the non-holding side; and of the teardrop sector,
#: which fills the rest of that half. The remaining 180° is the direct entry.
PARALLEL_ENTRY_SECTOR_DEG: float = 110.0
TEARDROP_ENTRY_SECTOR_DEG: float = 70.0

#: How far before the fix a hold *entry* placement sits, nautical miles. Far
#: enough that the student flies the entry rather than arriving mid-turn, close
#: enough that the fix is the next thing that happens.
DEFAULT_HOLD_ENTRY_DISTANCE_NM: float = 3.0

#: ICAO approach categories. PANS-OPS (Doc 8168) sorts aircraft into five
#: categories by ``Vat`` — the indicated airspeed at the threshold at maximum
#: certificated landing mass — and publishes the speeds each category flies a
#: procedure at. It is the coarsest classification that still separates a
#: trainer from an airliner, and unlike a performance table it is a *published*
#: property of the aeroplane rather than something this project would have to
#: invent.
ApproachCategory = Literal["A", "B", "C", "D", "E"]

#: Upper bound of each category's ``Vat`` band, in knots indicated. The bands
#: are A: below 91, B: 91 to 120, C: 121 to 140, D: 141 to 165, E: 166 to 210,
#: so these are the threshold speeds of the *fastest* aeroplane each category
#: admits.
#:
#: Taking the top of the band rather than its middle is deliberate, because the
#: two ways of being wrong are not symmetric. An aircraft handed too much speed
#: decelerates and the student flies on; an aircraft handed too little stalls
#: and the training session is over — which is the whole reason this table
#: exists. The top of the band is by construction at or above the threshold
#: speed of every aeroplane in the category.
#:
#: **What these numbers are not.** They are approach speeds, not cruise speeds,
#: and they are per *category*, not per airframe: within category C a light
#: business jet and a 737 land 15 kt apart and neither is exactly 140. A caller
#: that knows the aircraft should pass ``ias_kt`` and ignore all of this.
#: Speed is also only half of the problem — a jet placed clean at 140 kt is
#: still near its stall, because the flaps and gear that make that speed safe
#: are part of the full pre-teleport setup (issue #8), not of the geometry here.
APPROACH_CATEGORY_VAT_KT: Mapping[ApproachCategory, float] = MappingProxyType(
    {
        "A": 90.0,
        "B": 120.0,
        "C": 140.0,
        "D": 165.0,
        "E": 210.0,
    }
)

#: Maximum indicated airspeed for visual manoeuvring (circling) in each
#: category, knots — published alongside the ``Vat`` bands, and the speed a
#: circuit is flown at rather than the speed it is landed at. Used for circuit
#: legs and, as a generic manoeuvring speed, for a bare waypoint. Same caveats
#: as :data:`APPROACH_CATEGORY_VAT_KT`.
APPROACH_CATEGORY_CIRCLING_IAS_KT: Mapping[ApproachCategory, float] = MappingProxyType(
    {
        "A": 100.0,
        "B": 135.0,
        "C": 180.0,
        "D": 205.0,
        "E": 240.0,
    }
)

#: How PANS-OPS defines the threshold speed the category bands are read with:
#: ``Vat`` is **1.3 x the stall speed in the landing configuration (Vso)** at
#: maximum certificated landing mass. This is the published definition, not a
#: tuning knob — it is what lets a stall speed read from the loaded airframe
#: stand in for a category the caller did not state (issue #82).
#:
#: The honest caveat: a simulator reports the aircraft file's ``Vso``, which is
#: not necessarily quoted at maximum landing mass. A ``Vso`` quoted light reads
#: the band low — but the band it lands in is off by one at worst, against the
#: pre-#82 status quo of assuming category B for a category A trainer and
#: putting it on final 30 kt fast.
VAT_FROM_VSO: float = 1.3

#: The category assumed when the caller does not state one.
#:
#: **B, not A.** A caller who says nothing is most likely to be wrong on the
#: slow side, and slow is the failure that kills: category A speeds put a jet
#: below its stall, while category B speeds (120 kt on final) are merely a fast
#: approach in a trainer — still under a C172's never-exceed speed. A heavy
#: aircraft placed without a category is under-speeded even so. That is a
#: limitation of guessing, not something a different constant would fix; it is
#: why ``category`` is a parameter.
DEFAULT_APPROACH_CATEGORY: ApproachCategory = "B"

#: The speed of a placement that is not flying: a gate, a stand, a runway
#: threshold for a takeoff brief. Zero is the right answer exactly here and
#: nowhere else.
GROUND_IAS_KT: float = 0.0

#: Horizontal feet covered per minute for each knot of ground speed:
#: 6076.115486 ft per NM / 60 min ≈ 101.269. The descent arithmetic on a final
#: is built on it — ground speed ≈ IAS at approach altitudes (and in the still
#: air of a placement they are equal by construction), so the rate that holds a
#: glidepath is ``ias_kt · this · tan(glideslope)``: -478 fpm for 90 kt on a
#: 3° slope, which is the number a pilot expects to see on the VSI.
FEET_PER_MINUTE_PER_KNOT: float = FEET_PER_NAUTICAL_MILE / 60.0

#: The throttle and trim each placement profile hands over.
#:
#: **A hand-off state for a pilot, not a flight model.** These are fixed,
#: airframe-generic constants — approach power and a touch of nose-up trim for
#: a 3° descent in landing configuration — deliberately of the same honesty
#: class as the category speed tables above: named here, disclosed verbatim in
#: the preview notes, and always overridable by the instructor's sparse setup
#: overlay, which wins by the existing merge order. Per-airframe trim curves
#: are out of scope on purpose: a pilot is at the controls in a real session
#: (issue #81's own framing), so the profile only has to hand over an
#: aeroplane *near* its trimmed state instead of diverging away from it.
FINAL_THROTTLE: float = 0.30
FINAL_TRIM: float = 0.10
CIRCUIT_THROTTLE: float = 0.50
CRUISE_THROTTLE: float = 0.60

#: Flap settings, same honesty class as the throttle and trim constants above.
#: A final gets a mid-setting rather than full landing flap because full flap
#: at a category-table speed exceeds a jet's Vfe — 0.5 is survivable
#: everywhere. A base leg gets the first notch; every other leg is clean.
FINAL_FLAPS_RATIO: float = 0.5
BASE_FLAPS_RATIO: float = 0.25

#: Distance out from the threshold, in nautical miles, for each named final.
FINAL_DISTANCES_NM: Mapping[FinalPlacement, float] = MappingProxyType(
    {
        "final_20nm": 20.0,
        "final_15nm": 15.0,
        "final_10nm": 10.0,
        "final_8nm": 8.0,
        "final_5nm": 5.0,
        "final_3nm": 3.0,
        "short_final": SHORT_FINAL_DISTANCE_NM,
    }
)

#: Leg and pattern side behind each named circuit placement.
PATTERN_PLACEMENTS: Mapping[PatternPlacement, tuple[PatternLeg, PatternSide]] = MappingProxyType(
    {
        "left_upwind": ("upwind", "left"),
        "left_crosswind": ("crosswind", "left"),
        "left_downwind": ("downwind", "left"),
        "left_base": ("base", "left"),
        "right_upwind": ("upwind", "right"),
        "right_crosswind": ("crosswind", "right"),
        "right_downwind": ("downwind", "right"),
        "right_base": ("base", "right"),
    }
)

#: The full catalogue of runway-relative placements, in menu order.
RUNWAY_PLACEMENTS: tuple[RunwayPlacement, ...] = (*FINAL_DISTANCES_NM, *PATTERN_PLACEMENTS)

_WGS84: Geodesic = Geodesic.WGS84

#: 1 kt = 1852 m / 3600 s = 0.514444 m/s. Exact, by the definition above.
_METRES_PER_SECOND_PER_KNOT: float = METRES_PER_NAUTICAL_MILE / 3600.0

#: Standard gravity, m/s². Only a turn radius needs it, and only through
#: ``v² / (g tan φ)``.
_STANDARD_GRAVITY_M_PER_S2: float = 9.806_65


class Placement(BaseModel):
    """A resolved placement: where to put the aircraft, facing where, doing what speed.

    Everything an instructor station needs to reposition, and nothing about how
    the repositioning happens — writing it is the adapter's job.

    ``ias_kt`` and ``profile`` have **no default on purpose**. They are the two
    fields of this model that cannot be inferred from geometry, and leaving the
    speed out is precisely the defect that put an aircraft on a perfect 10 NM
    final at 0 kt — so a new placement type cannot be written without answering
    both questions: how fast, and what kind of flying this is.
    """

    model_config = ConfigDict(frozen=True)

    position: GeoPosition = Field(
        description="Target position; its altitude_ft is the target altitude, feet MSL."
    )
    heading_deg: float = Field(
        ge=0.0, lt=360.0, description="True heading to fly at that point, degrees."
    )
    ias_kt: float = Field(
        ge=0.0,
        description=(
            "Indicated airspeed to command at that point, knots. Zero only for a "
            "placement that is not flying — a gate, a stand, a runway threshold."
        ),
    )
    label: str = Field(
        min_length=1,
        description='Human-readable description, e.g. "LEMD 32L 10 NM final".',
    )
    profile: PlacementProfile = Field(
        description=(
            "What kind of flying this placement is; decides the configuration to_setup() "
            "emits. Required, no default — the same philosophy as ias_kt: a new placement "
            "type cannot be written without answering the question."
        )
    )
    ils: Ils | None = Field(
        default=None,
        description=(
            "The ILS an approach placement is flown to, when the runway publishes one. "
            "to_setup() tunes NAV1 and the OBS from it, so no caller can place an aircraft "
            "on an approach while forgetting the radios. Finals only."
        ),
    )
    glideslope_deg: float | None = Field(
        default=None,
        gt=0.0,
        description="Glidepath angle in degrees; the descent rate follows from it. Finals only.",
    )
    pattern_leg: PatternLeg | None = Field(
        default=None,
        description="Which leg of the circuit; gear and flaps differ per leg. Circuit only.",
    )

    @property
    def altitude_ft(self) -> float:
        """Target altitude in feet MSL — the same value as ``position.altitude_ft``."""
        return self.position.altitude_ft

    def to_setup(self) -> AircraftSetup:
        """The aircraft state to apply **before** the reposition is written.

        Three fields come from the geometry — altitude, heading and speed —
        and the rest from the placement's :attr:`profile`, because a short
        final is configured (gear, flaps, throttle, trim, descent, radios) and
        a hold is merely flown level and clean. Speed alone is not a stabilised
        approach; the profile's configuration is the rest of it (issue #8).
        Anything the profile does not determine is left ``None``, which an
        adapter reads as *leave that aspect untouched*.
        """
        return AircraftSetup(
            altitude_ft=self.position.altitude_ft,
            heading_deg=self.heading_deg,
            ias_kt=self.ias_kt,
            **_profile_setup(self),
        )


def _profile_setup(placement: Placement) -> dict[str, Any]:
    """The configuration a placement's profile adds to its geometry.

    One table, four rows. The numbers are the module's named hand-off
    constants — see :data:`FINAL_THROTTLE` for what they are worth and why
    they are deliberately airframe-generic.
    """
    profile = placement.profile
    if profile == "final":
        setup: dict[str, Any] = {
            "gear_down": True,
            "flaps_ratio": FINAL_FLAPS_RATIO,
            "throttle_ratio": FINAL_THROTTLE,
            "elevator_trim_ratio": FINAL_TRIM,
            "roll_deg": 0.0,
            "lights": LightsSetup(landing=True),
        }
        if placement.glideslope_deg is not None:
            # In the still air of a placement ground speed equals IAS, one knot
            # covers FEET_PER_MINUTE_PER_KNOT feet of ground per minute, and the
            # rate that holds the slope is that run times its gradient: -478 fpm
            # for 90 kt on 3°. Without it the aircraft arrives level, 0 fpm on a
            # 3° path, and immediately diverges from the glideslope (#81).
            setup["vertical_speed_fpm"] = -(
                placement.ias_kt
                * FEET_PER_MINUTE_PER_KNOT
                * math.tan(math.radians(placement.glideslope_deg))
            )
        if placement.ils is not None:
            setup["nav1_freq_khz"] = placement.ils.frequency_khz
            setup["obs1_deg"] = placement.ils.localizer_mag_deg
        return setup
    if profile == "circuit":
        # Configuration follows the leg: the aircraft configures as it comes
        # round the circuit, so downwind and base carry the gear and base the
        # first notch of flap, while upwind and crosswind are still clean.
        leg = placement.pattern_leg
        return {
            "gear_down": leg in ("downwind", "base"),
            "flaps_ratio": BASE_FLAPS_RATIO if leg == "base" else 0.0,
            "throttle_ratio": CIRCUIT_THROTTLE,
            "elevator_trim_ratio": 0.0,
            "roll_deg": 0.0,
            "vertical_speed_fpm": 0.0,
        }
    if profile == "airborne":
        return {
            "gear_down": False,
            "flaps_ratio": 0.0,
            "throttle_ratio": CRUISE_THROTTLE,
            "elevator_trim_ratio": 0.0,
            "roll_deg": 0.0,
            "vertical_speed_fpm": 0.0,
        }
    if profile == "ground":
        # Roll and vertical speed are deliberately left None: the aircraft is
        # sitting on its gear and both belong to the terrain, not the placement.
        return {
            "gear_down": True,
            "flaps_ratio": 0.0,
            "throttle_ratio": 0.0,
            "elevator_trim_ratio": 0.0,
        }
    assert_never(profile)  # pragma: no cover - exhaustive over PlacementProfile


def _normalise_bearing(bearing_deg: float) -> float:
    """Fold any angle in degrees into ``[0, 360)``."""
    return bearing_deg % 360.0


def _direct(
    origin: GeoPosition,
    distance_nm: float,
    bearing_deg: float,
) -> tuple[GeoPosition, float]:
    """Direct geodesic problem, also returning the bearing at the far end.

    The two bearings differ by the convergence of the meridians, so a caller
    that carries on from the destination has to continue on the *arrival*
    bearing rather than the one it set out on.
    """
    result = _WGS84.Direct(
        origin.latitude,
        origin.longitude,
        _normalise_bearing(bearing_deg),
        distance_nm * METRES_PER_NAUTICAL_MILE,
    )
    destination = GeoPosition(
        latitude=float(result["lat2"]),
        longitude=float(result["lon2"]),
        altitude_ft=origin.altitude_ft,
    )
    return destination, _normalise_bearing(float(result["azi2"]))


def point_at_distance_and_bearing(
    origin: GeoPosition,
    distance_nm: float,
    bearing_deg: float,
) -> GeoPosition:
    """Solve the direct geodesic problem.

    Args:
        origin: Starting point. Its ``altitude_ft`` is carried over unchanged.
        distance_nm: Geodesic distance to travel, in nautical miles. Negative
            values travel backwards along the same line.
        bearing_deg: Initial true bearing in degrees.

    Returns:
        The destination point, at the same altitude as ``origin``.
    """
    destination, _ = _direct(origin, distance_nm, bearing_deg)
    return destination


def distance_and_bearing(a: GeoPosition, b: GeoPosition) -> tuple[float, float]:
    """Solve the inverse geodesic problem.

    Args:
        a: Origin point.
        b: Destination point.

    Returns:
        ``(distance_nm, initial_true_bearing_deg)`` — the horizontal geodesic
        distance in nautical miles and the initial true bearing from ``a`` to
        ``b`` in degrees, normalised to ``[0, 360)``. Altitude is ignored.
    """
    result = _WGS84.Inverse(a.latitude, a.longitude, b.latitude, b.longitude)
    distance_nm = float(result["s12"]) / METRES_PER_NAUTICAL_MILE
    return distance_nm, _normalise_bearing(float(result["azi1"]))


def glideslope_altitude_ft(
    threshold_elevation_ft: float,
    distance_nm: float,
    glideslope_deg: float = DEFAULT_GLIDESLOPE_DEG,
) -> float:
    """Altitude of a constant-angle glidepath at a given distance from threshold.

    Args:
        threshold_elevation_ft: Runway threshold elevation, feet MSL.
        distance_nm: Along-track distance from the threshold, nautical miles.
        glideslope_deg: Glidepath angle in degrees (3.0 is the ICAO standard).

    Returns:
        Altitude in feet MSL. Uses the flat-earth approximation
        ``elev + tan(gs) * distance_nm * FEET_PER_NAUTICAL_MILE``, which is
        what published approach charts do and is accurate well beyond the
        distances an instructor station repositions at.
    """
    return threshold_elevation_ft + math.tan(math.radians(glideslope_deg)) * (
        distance_nm * FEET_PER_NAUTICAL_MILE
    )


def final_approach_point(
    runway: Runway,
    distance_nm: float,
    glideslope_deg: float = DEFAULT_GLIDESLOPE_DEG,
) -> GeoPosition:
    """Point on the extended runway centreline, on the glidepath.

    **The origin is the displaced landing threshold**, ``runway.threshold`` —
    never the start of the pavement, which :class:`~core.models.Runway` carries
    separately as ``pavement_end``. That is what an aircraft on final aims at and
    what a published approach is measured from, and the distinction is not
    cosmetic: at LEMD 18L the two points are ~496 m apart, so anchoring here on
    the pavement end would place a "10 NM final" 0.27 NM out of position, every
    time, with the geometry looking perfect.

    Args:
        runway: The target runway end.
        distance_nm: Distance out from the **landing threshold**, nautical
            miles.
        glideslope_deg: Glidepath angle in degrees.

    Returns:
        A position ``distance_nm`` before the threshold along the extended
        centreline (bearing = runway bearing + 180°), at the glidepath altitude
        for that distance in feet MSL. The heading to fly from there is the
        runway's ``true_bearing_deg``.
    """
    reciprocal = _normalise_bearing(runway.true_bearing_deg + 180.0)
    point = point_at_distance_and_bearing(runway.threshold, distance_nm, reciprocal)
    return GeoPosition(
        latitude=point.latitude,
        longitude=point.longitude,
        altitude_ft=glideslope_altitude_ft(runway.elevation_ft, distance_nm, glideslope_deg),
    )


def _offset(
    origin: GeoPosition,
    along_nm: float,
    across_nm: float,
    axis_bearing_deg: float,
    altitude_ft: float,
) -> GeoPosition:
    """Move ``along_nm`` down the axis, then ``across_nm`` perpendicular to it.

    ``across_nm`` is positive to the *right* of the axis. Both legs are solved
    as geodesics, so the result is exact at pattern scale and beyond.

    The perpendicular is taken from the axis bearing *where the leg leaves the
    centreline*, not from the bearing back at ``origin``: the meridians
    converge along the way, and turning off on the stale bearing skews the two
    sides of the pattern by about a metre in opposite directions instead of
    leaving them exact mirror images of each other.
    """
    axis = _normalise_bearing(axis_bearing_deg)
    moved, axis_at_turn = _direct(origin, along_nm, axis)
    if across_nm != 0.0:
        perpendicular = axis_at_turn + 90.0 * math.copysign(1.0, across_nm)
        moved = point_at_distance_and_bearing(moved, abs(across_nm), perpendicular)
    return GeoPosition(
        latitude=moved.latitude,
        longitude=moved.longitude,
        altitude_ft=altitude_ft,
    )


def traffic_pattern_point(
    runway: Runway,
    leg: PatternLeg,
    pattern_altitude_ft: float,
    pattern_width_nm: float = DEFAULT_PATTERN_WIDTH_NM,
    leg_distance_nm: float = DEFAULT_PATTERN_LEG_DISTANCE_NM,
    left_hand: bool = True,
) -> tuple[GeoPosition, float]:
    """Position and heading for a point on a rectangular traffic pattern.

    Geometry is built on the runway axis, with the **displaced landing
    threshold** (``runway.threshold``) as origin and the **pavement length**
    (``runway.length_m``) as the along-axis span — the two halves of the
    convention :class:`~core.models.Runway` pins, taken here deliberately and
    together. A pattern is flown relative to the runway the pilot sees, so the
    downwind abeam point sits at half the *paved* length from the threshold, and
    on a runway with a displaced threshold the upwind and crosswind legs
    therefore sit ``displaced_threshold_m`` further out than the far end of the
    pavement. That is the conservative direction — the legs are never *short* of
    the departure end — and it is why ``length_m`` is the pavement length rather
    than the landing distance available.

    The pattern lies on the left of the runway when ``left_hand`` is true (all
    turns to the left), on the right otherwise.

    Args:
        runway: The runway the pattern is flown around.
        leg: Which leg to position on.
        pattern_altitude_ft: Pattern altitude, feet MSL.
        pattern_width_nm: Lateral distance from the centreline to the downwind
            leg, in nautical miles.
        leg_distance_nm: How far beyond the departure end the upwind/crosswind
            legs sit, and how far before the landing threshold the base leg
            sits, in nautical miles.
        left_hand: ``True`` for a left-hand (standard) pattern.

    Returns:
        ``(position, recommended_heading_deg)`` — the position at pattern
        altitude and the true heading to fly that leg, in degrees.
    """
    axis = _normalise_bearing(runway.true_bearing_deg)
    length_nm = runway.length_m / METRES_PER_NAUTICAL_MILE
    # Positive "across" is to the right of the axis; the pattern side is left
    # for a standard pattern.
    side = -1.0 if left_hand else 1.0
    # In a left-hand pattern every turn is to the left: crosswind is the
    # runway heading minus 90°, base is the runway heading plus 90°.
    turn = -90.0 if left_hand else 90.0

    if leg == "upwind":
        along_nm = length_nm + leg_distance_nm
        across_nm = 0.0
        heading = axis
    elif leg == "crosswind":
        along_nm = length_nm + leg_distance_nm
        across_nm = side * pattern_width_nm / 2.0
        heading = axis + turn
    elif leg == "downwind":
        along_nm = length_nm / 2.0
        across_nm = side * pattern_width_nm
        heading = axis + 180.0
    elif leg == "base":
        along_nm = -leg_distance_nm
        across_nm = side * pattern_width_nm
        heading = axis - turn
    else:  # pragma: no cover - exhaustive over PatternLeg
        assert_never(leg)

    position = _offset(runway.threshold, along_nm, across_nm, axis, pattern_altitude_ft)
    return position, _normalise_bearing(heading)


# ---------------------------------------------------------------------------
# Placements
# ---------------------------------------------------------------------------


def _arrival_bearing(origin: GeoPosition, destination: GeoPosition) -> float:
    """True bearing *at* ``destination`` of the geodesic flown from ``origin``.

    This is the azimuth at the far end of the line, not the initial one
    :func:`distance_and_bearing` returns. Over a long leg the two differ by the
    convergence of the meridians — 6.4° on a 10° change of longitude at 40°
    latitude — and it is the arrival value that says which way the aircraft is
    pointing when it gets there.
    """
    result = _WGS84.Inverse(
        origin.latitude,
        origin.longitude,
        destination.latitude,
        destination.longitude,
    )
    return _normalise_bearing(float(result["azi2"]))


def _runway_label(runway: Runway, what: str) -> str:
    """``"LEMD 32L 10 NM final"`` and friends."""
    return f"{runway.airport_icao} {runway.ident} {what}"


def _resolve_ias_kt(
    ias_kt: float | None,
    table: Mapping[ApproachCategory, float],
    category: ApproachCategory,
) -> float:
    """The caller's speed when it stated one, the category's default otherwise.

    An explicit value always wins: only the caller can know the airframe, and a
    category is a coarse stand-in for it.
    """
    return table[category] if ias_kt is None else ias_kt


def _constrained_ias_kt(
    ias_kt: float | None,
    category: ApproachCategory,
    *,
    min_kt: float | None = None,
    max_kt: float | None = None,
) -> float:
    """A manoeuvring speed for the category, folded into a *published* band.

    Navdata publishes speed **restrictions**, not target speeds: a hold placarded
    at 230 kt and a STAR leg placarded at 250 kt are ceilings that a Cessna is
    never expected to reach. Flying the placard would put a category A trainer
    100 kt over its manoeuvring speed, so the aircraft's own circling speed is
    the starting point and the published values only clamp it.

    An explicit ``ias_kt`` bypasses the whole thing: a caller that names a speed
    knows the airframe, which is more than either the category table or the
    chart does.

    The result is never below the category's threshold speed, whatever the
    source says. An implausibly low published ceiling — a mis-parsed field, a
    restriction meant for a different aircraft class — must not be able to hand
    an aeroplane a stall, which is the exact failure mode issue #39 exists for.
    """
    if ias_kt is not None:
        return ias_kt
    speed = APPROACH_CATEGORY_CIRCLING_IAS_KT[category]
    if max_kt is not None:
        speed = min(speed, max_kt)
    if min_kt is not None:
        speed = max(speed, min_kt)
    return max(speed, APPROACH_CATEGORY_VAT_KT[category])


def category_for_vat(vat_kt: float) -> ApproachCategory:
    """The ICAO approach category whose published ``Vat`` band contains ``vat_kt``.

    The PANS-OPS bands, by threshold speed: A below 91 kt, B 91-120, C 121-140,
    D 141-165, E 166-210. The comparisons are ``< 91``, ``< 121`` and so on, so
    a computed value falling in one of the table's integer gaps (120.4 kt, say)
    reads as the slower band — the one whose procedure speeds it can actually
    fly.

    **Above 210 kt the table simply ends** — there is no category F — so the
    answer is clamped to ``"E"`` rather than invented: E's speeds are the
    fastest any chart publishes, and an aeroplane beyond them is at least
    handed the fastest of them instead of an exception.

    Zero or negative is a **caller bug**, not a data condition, and raises
    :class:`ValueError`. Every ``Vat`` computed in this project is
    :data:`VAT_FROM_VSO` times a stall speed that
    :class:`~core.models.AirframeInfo` validates as strictly positive, so a
    non-positive value means the arithmetic went wrong upstream — it must not
    be laundered into "category A".
    """
    if vat_kt <= 0.0:
        raise ValueError(f"Vat must be a positive speed in knots, got {vat_kt!r}.")
    if vat_kt < 91.0:
        return "A"
    if vat_kt < 121.0:
        return "B"
    if vat_kt < 141.0:
        return "C"
    if vat_kt < 166.0:
        return "D"
    return "E"


def _position_of(fix: GeoPosition | Waypoint) -> GeoPosition:
    """Accept either a bare point or a navdata waypoint wherever a point is wanted."""
    return fix if isinstance(fix, GeoPosition) else fix.position


def _contextual_heading_deg(
    point: GeoPosition,
    heading_deg: float | None,
    next_fix: GeoPosition | Waypoint | None,
    previous_fix: GeoPosition | Waypoint | None,
) -> float:
    """The heading to face at a bare fix, in order of preference.

    1. ``heading_deg``, when the caller states one — an explicit choice always
       wins.
    2. The initial true bearing towards ``next_fix``: the aircraft arrives
       already tracking the leg it is about to fly.
    3. The bearing at which the leg from ``previous_fix`` *arrives* over the
       point, so the aircraft appears established on the inbound course. This is
       the final bearing of that geodesic, not its initial one.
    4. Failing all of that, due north — arbitrary, but deterministic and
       obvious, rather than pretending a direction was inferred.

    A published magnetic course is never used as a fallback here: this module is
    true throughout, and converting one needs a magnetic model the project does
    not carry. A caller holding a variation converts it with
    :func:`true_from_magnetic` and passes the result as ``heading_deg``.
    """
    if heading_deg is not None:
        return _normalise_bearing(heading_deg)
    if next_fix is not None:
        _, bearing = distance_and_bearing(point, _position_of(next_fix))
        return bearing
    if previous_fix is not None:
        return _arrival_bearing(_position_of(previous_fix), point)
    return 0.0


def true_from_magnetic(magnetic_deg: float, variation_deg: float) -> float:
    """Convert a published magnetic course to a true one.

    Args:
        magnetic_deg: The published course, magnetic degrees.
        variation_deg: Local magnetic variation, degrees, **positive east** —
            the convention ``apt.dat`` and ``earth_nav.dat`` publish.

    Returns:
        The true course, normalised to ``[0, 360)``: ``magnetic + variation``.
        "East is least, west is best" runs the other way because it converts
        *true to magnetic*; this is that identity rearranged.

    This is the only place in the project where the two frames meet, and it is
    deliberately a function the caller has to reach for: ``core/`` carries no
    world magnetic model, so the variation is always something the caller read
    from navdata rather than something this module can look up.
    """
    return _normalise_bearing(magnetic_deg + variation_deg)


def final_placement(
    runway: Runway,
    placement: FinalPlacement,
    *,
    glideslope_deg: float = DEFAULT_GLIDESLOPE_DEG,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
    ils: Ils | None = None,
) -> Placement:
    """Place the aircraft on a named final, on the glidepath, at approach speed.

    Args:
        runway: The runway being approached.
        placement: Which named final — see :data:`FINAL_DISTANCES_NM` for the
            distance out, in nautical miles, that each name resolves to.
        glideslope_deg: Glidepath angle in degrees.
        ias_kt: Indicated airspeed to command, knots. ``None`` takes the
            ``category``'s threshold speed from :data:`APPROACH_CATEGORY_VAT_KT`.
        category: The aircraft's ICAO approach category, used only when
            ``ias_kt`` is ``None``.
        ils: The ILS serving this approach, when the runway publishes one —
            typically ``runway.ils``. Carried on the placement so its setup
            tunes NAV1 and the OBS, and the radios arrive with the geometry.

    Returns:
        A :class:`Placement` on the extended centreline at the glidepath
        altitude for that distance (feet MSL), heading down the runway
        centreline in true degrees, at an approach speed. **Never at 0 kt** —
        a final is by definition flown, and the speed is commanded here rather
        than inherited from whatever the aircraft happened to be doing.
    """
    distance_nm = FINAL_DISTANCES_NM[placement]
    what = "short final" if placement == "short_final" else f"{distance_nm:g} NM final"
    return Placement(
        position=final_approach_point(runway, distance_nm, glideslope_deg),
        heading_deg=_normalise_bearing(runway.true_bearing_deg),
        ias_kt=_resolve_ias_kt(ias_kt, APPROACH_CATEGORY_VAT_KT, category),
        label=_runway_label(runway, what),
        profile="final",
        ils=ils,
        glideslope_deg=glideslope_deg,
    )


def pattern_placement(
    runway: Runway,
    placement: PatternPlacement,
    *,
    pattern_altitude_ft: float | None = None,
    pattern_width_nm: float = DEFAULT_PATTERN_WIDTH_NM,
    leg_distance_nm: float = DEFAULT_PATTERN_LEG_DISTANCE_NM,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
) -> Placement:
    """Place the aircraft on a named circuit leg, at circuit speed.

    Args:
        runway: The runway the pattern is flown around.
        placement: Which leg, and which side the pattern is flown on — see
            :data:`PATTERN_PLACEMENTS`.
        pattern_altitude_ft: Pattern altitude in feet MSL. ``None`` uses the
            standard :data:`DEFAULT_PATTERN_ALTITUDE_AGL_FT` above the runway
            threshold elevation.
        pattern_width_nm: Lateral distance from the centreline to the downwind
            leg, nautical miles.
        leg_distance_nm: How far beyond the departure end the upwind/crosswind
            legs sit, and how far before the threshold the base leg sits,
            nautical miles.
        ias_kt: Indicated airspeed to command, knots. ``None`` takes the
            ``category``'s circling speed from
            :data:`APPROACH_CATEGORY_CIRCLING_IAS_KT` — a circuit is flown
            faster than it is landed, so this is not the final approach speed.
        category: The aircraft's ICAO approach category, used only when
            ``ias_kt`` is ``None``.

    Returns:
        A :class:`Placement` at pattern altitude and circuit speed, heading down
        that leg. The right-hand pattern is the mirror image of the left-hand
        one about the runway centreline.
    """
    leg, side = PATTERN_PLACEMENTS[placement]
    altitude_ft = (
        runway.elevation_ft + DEFAULT_PATTERN_ALTITUDE_AGL_FT
        if pattern_altitude_ft is None
        else pattern_altitude_ft
    )
    position, heading_deg = traffic_pattern_point(
        runway,
        leg,
        altitude_ft,
        pattern_width_nm,
        leg_distance_nm,
        left_hand=side == "left",
    )
    return Placement(
        position=position,
        heading_deg=heading_deg,
        ias_kt=_resolve_ias_kt(ias_kt, APPROACH_CATEGORY_CIRCLING_IAS_KT, category),
        label=_runway_label(runway, f"{side}-hand {leg}"),
        profile="circuit",
        pattern_leg=leg,
    )


def resolve_runway_placement(
    runway: Runway,
    placement: RunwayPlacement,
    *,
    glideslope_deg: float = DEFAULT_GLIDESLOPE_DEG,
    pattern_altitude_ft: float | None = None,
    pattern_width_nm: float = DEFAULT_PATTERN_WIDTH_NM,
    leg_distance_nm: float = DEFAULT_PATTERN_LEG_DISTANCE_NM,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
    ils: Ils | None = None,
) -> Placement:
    """Resolve any name in :data:`RUNWAY_PLACEMENTS` against a runway.

    The single entry point for runway-relative placements: an API layer can
    enumerate :data:`RUNWAY_PLACEMENTS`, take a name from the request and call
    this, without knowing which names are finals and which are circuit legs.

    Args:
        runway: The runway the placement is relative to.
        placement: Any name in :data:`RUNWAY_PLACEMENTS`.
        glideslope_deg: Glidepath angle in degrees. Finals only.
        pattern_altitude_ft: Pattern altitude in feet MSL, or ``None`` for the
            standard height above the field. Circuit legs only.
        pattern_width_nm: Lateral distance from the centreline to the downwind
            leg, nautical miles. Circuit legs only.
        leg_distance_nm: Upwind/crosswind and base leg offsets, nautical miles.
            Circuit legs only.
        ias_kt: Indicated airspeed to command, knots, for either kind of
            placement. ``None`` defers to ``category``, which resolves to an
            approach speed on a final and a circling speed on a circuit leg.
        category: The aircraft's ICAO approach category, used only when
            ``ias_kt`` is ``None``.
        ils: The ILS serving the runway end, when one is published — typically
            ``runway.ils``, passed explicitly so a caller resolving a
            non-precision exercise on an ILS runway can withhold it. Finals
            only; a circuit is flown visually.

    Returns:
        The resolved :class:`Placement`, always with a flying speed.
    """
    match placement:
        case (
            "final_20nm"
            | "final_15nm"
            | "final_10nm"
            | "final_8nm"
            | "final_5nm"
            | "final_3nm"
            | "short_final"
        ):
            return final_placement(
                runway,
                placement,
                glideslope_deg=glideslope_deg,
                ias_kt=ias_kt,
                category=category,
                ils=ils,
            )
        case (
            "left_upwind"
            | "left_crosswind"
            | "left_downwind"
            | "left_base"
            | "right_upwind"
            | "right_crosswind"
            | "right_downwind"
            | "right_base"
        ):
            return pattern_placement(
                runway,
                placement,
                pattern_altitude_ft=pattern_altitude_ft,
                pattern_width_nm=pattern_width_nm,
                leg_distance_nm=leg_distance_nm,
                ias_kt=ias_kt,
                category=category,
            )
        case _:  # pragma: no cover - exhaustive over RunwayPlacement
            assert_never(placement)


def coordinate_placement(
    position: GeoPosition,
    heading_deg: float = 0.0,
    *,
    ias_kt: float = GROUND_IAS_KT,
) -> Placement:
    """Place the aircraft at an arbitrary coordinate.

    Args:
        position: Where to put it. ``altitude_ft`` is the target altitude,
            feet MSL.
        heading_deg: True heading in degrees; folded into ``[0, 360)``.
        ias_kt: Indicated airspeed to command, knots. Defaults to
            :data:`GROUND_IAS_KT`.

    Returns:
        The placement, verbatim — nothing about a free coordinate is derived,
        and that includes its speed. A bare latitude/longitude is as likely a
        parking stand as a cruise level, so guessing would be inventing: the
        default is *stationary*, and a caller putting the aircraft **airborne**
        must state ``ias_kt`` or it will arrive below stall speed. That is why
        this is the only placement in the module whose default is 0 kt.

        The profile follows the speed: 0 kt is definitionally not flying, so a
        stationary coordinate is ``"ground"`` — gear down, everything at idle —
        and any other speed is ``"airborne"``.
    """
    return Placement(
        position=position,
        heading_deg=_normalise_bearing(heading_deg),
        ias_kt=ias_kt,
        label=f"{position.latitude:.4f}, {position.longitude:.4f}",
        profile="ground" if ias_kt == GROUND_IAS_KT else "airborne",
    )


def waypoint_placement(
    waypoint: GeoPosition | Waypoint,
    altitude_ft: float,
    *,
    ident: str | None = None,
    heading_deg: float | None = None,
    next_fix: GeoPosition | Waypoint | None = None,
    previous_fix: GeoPosition | Waypoint | None = None,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
) -> Placement:
    """Place the aircraft over a waypoint at a chosen altitude.

    A waypoint is a bare point: it carries no heading of its own, so one has to
    be chosen. In order of preference, the *sensible* heading is:

    1. ``heading_deg``, when the caller states one — an explicit choice always
       wins.
    2. The initial true bearing from the waypoint to ``next_fix``: the aircraft
       arrives already tracking the leg it is about to fly.
    3. The bearing at which the leg from ``previous_fix`` *arrives* over the
       waypoint, so the aircraft appears established on the inbound course.
       This is the final bearing of that geodesic, not its initial one.
    4. Failing all of that, due north (0°) — arbitrary, but deterministic and
       obvious, rather than pretending a direction was inferred.

    Args:
        waypoint: The fix to sit over, either as a bare point or as a
            :class:`~core.navdata.models.Waypoint` straight out of the navdata
            index. Its own ``altitude_ft`` is ignored in favour of
            ``altitude_ft``, because navdata fixes carry no altitude.
        altitude_ft: Target altitude, feet MSL.
        ident: Fix name, used only for the label. ``None`` takes the ident of a
            navdata waypoint, and falls back to ``"waypoint"`` for a bare point.
        heading_deg: Explicit true heading in degrees, or ``None``.
        next_fix: The fix the aircraft would fly to next, or ``None``.
        previous_fix: The fix the aircraft would be coming from, or ``None``.
        ias_kt: Indicated airspeed to command, knots. ``None`` takes the
            ``category``'s circling speed from
            :data:`APPROACH_CATEGORY_CIRCLING_IAS_KT`, used here as a generic
            manoeuvring speed: enough to fly, and not a cruise speed. A caller
            dropping the aircraft into the cruise should pass its cruise speed.
        category: The aircraft's ICAO approach category, used only when
            ``ias_kt`` is ``None``.

    Returns:
        The placement over the waypoint at ``altitude_ft``, flying. Unlike a
        free coordinate, a waypoint is always airborne — it is a navdata fix
        with a stated altitude — so a speed is defaulted rather than withheld.
    """
    point = _position_of(waypoint)
    if ident is None:
        ident = waypoint.ident if isinstance(waypoint, Waypoint) else "waypoint"
    return Placement(
        position=GeoPosition(
            latitude=point.latitude,
            longitude=point.longitude,
            altitude_ft=altitude_ft,
        ),
        heading_deg=_contextual_heading_deg(point, heading_deg, next_fix, previous_fix),
        ias_kt=_resolve_ias_kt(ias_kt, APPROACH_CATEGORY_CIRCLING_IAS_KT, category),
        label=f"over {ident}",
        profile="airborne",
    )


# ---------------------------------------------------------------------------
# Published holding patterns
# ---------------------------------------------------------------------------


def turn_radius_nm(
    tas_kt: float,
    rate_of_turn_deg_per_s: float = HOLD_RATE_OF_TURN_DEG_PER_S,
    max_bank_deg: float = HOLD_MAX_BANK_DEG,
) -> float:
    """Radius of a level turn flown to the ICAO holding criterion.

    Two constraints, and the aircraft flies whichever asks for **less bank**:
    a rate of ``rate_of_turn_deg_per_s`` (rate one, 3°/s, is a two-minute
    360°), or a bank of ``max_bank_deg``. Less bank is more radius, so the
    binding constraint is simply the larger of the two radii::

        rate:  r = V / (20 * pi * omega)      omega in degrees per second
        bank:  r = V^2 / (g * tan(phi))       V in metres per second

    They cross at about 170 kt true. A 120 kt trainer turns at rate one inside
    0.64 NM; a 210 kt jet cannot hold rate one within 25° of bank and needs
    1.38 NM.

    Args:
        tas_kt: **True** airspeed in knots — a turn is flown through the air
            mass, so an indicated speed understates the radius at altitude by
            the same factor the airspeed indicator does. Convert first with
            :func:`core.atmosphere.tas_from_ias`.
        rate_of_turn_deg_per_s: Standard rate of turn, degrees per second.
        max_bank_deg: Bank limit, degrees. Must be in ``(0, 90)``.

    Returns:
        The turn radius in nautical miles. Zero for a stationary aircraft,
        which is not a flying speed but is a defensible geometric answer.

    Raises:
        ValueError: if the speed is negative, the rate is not positive, or the
            bank is outside ``(0, 90)`` — none of which describe a turn.
    """
    if tas_kt < 0.0:
        raise ValueError(f"tas_kt={tas_kt} is negative; an aircraft does not fly backwards.")
    if rate_of_turn_deg_per_s <= 0.0:
        raise ValueError(
            f"rate_of_turn_deg_per_s={rate_of_turn_deg_per_s} is not positive; a turn that "
            "never comes round has no radius."
        )
    if not 0.0 < max_bank_deg < 90.0:
        raise ValueError(
            f"max_bank_deg={max_bank_deg} is outside (0, 90); a level turn needs some bank and "
            "cannot reach 90°, where the lift has no vertical component left."
        )
    rate_radius_nm = tas_kt / (20.0 * math.pi * rate_of_turn_deg_per_s)
    speed_m_per_s = tas_kt * _METRES_PER_SECOND_PER_KNOT
    bank_radius_nm = (
        speed_m_per_s**2 / (_STANDARD_GRAVITY_M_PER_S2 * math.tan(math.radians(max_bank_deg)))
    ) / METRES_PER_NAUTICAL_MILE
    return max(rate_radius_nm, bank_radius_nm)


def holding_entry(
    inbound_course_deg: float,
    arrival_course_deg: float,
    turn_direction: TurnDirection = "R",
) -> HoldEntry:
    """Which of the three ICAO entries an aircraft arriving on that course flies.

    The sectors are fixed relative to the inbound course, and for a standard
    (right-turn) hold they are, in terms of the arriving aircraft's track::

        inbound + 0°   .. +180°   direct     (180° — cross the fix and turn)
        inbound + 180° .. +290°   parallel   (110°)
        inbound + 290° .. +360°   teardrop   (70°)

    Read on a hold whose inbound course is 360°: arrive heading anywhere from
    north through east to south and the entry is direct; from south round to
    290° it is parallel; the last 70° back to north is the teardrop. A left-hand
    hold is the mirror image, so the offset is measured the other way round.

    Args:
        inbound_course_deg: Course flown *towards* the fix on the inbound leg.
        arrival_course_deg: Course the aircraft is flying when it reaches the
            fix. **In the same frame as** ``inbound_course_deg`` — both true or
            both magnetic. Mixing the two frames rotates every sector boundary
            by the local variation, which is what :func:`true_from_magnetic`
            exists to prevent.
        turn_direction: ``"R"`` for a standard right-hand hold, ``"L"`` for a
            non-standard left-hand one.

    Returns:
        ``"direct"``, ``"parallel"`` or ``"teardrop"``.

    A boundary belongs to the sector it opens: exactly on the reciprocal of the
    inbound course the answer is ``"parallel"``. Real procedure design allows a
    ±5° zone in which either adjacent entry may be flown; that discretion
    belongs to the pilot, not to a placement, so the answer here is always the
    single deterministic one.
    """
    offset_deg = _normalise_bearing(arrival_course_deg - inbound_course_deg)
    if turn_direction == "L":
        offset_deg = _normalise_bearing(-offset_deg)
    if offset_deg < 180.0:
        return "direct"
    if offset_deg < 180.0 + PARALLEL_ENTRY_SECTOR_DEG:
        return "parallel"
    return "teardrop"


def hold_entry(
    hold: Hold,
    arrival_course_true_deg: float,
    *,
    magnetic_variation_deg: float,
) -> HoldEntry:
    """The entry for a *published* hold, whose inbound course is magnetic.

    Args:
        hold: The published hold.
        arrival_course_true_deg: Course the aircraft is flying when it reaches
            the fix, **true** degrees.
        magnetic_variation_deg: Local variation, degrees positive east.
            Required, with no default: see the module docstring.

    Returns:
        The entry the aircraft would fly, from :func:`holding_entry` with both
        courses brought into the true frame.
    """
    return holding_entry(
        true_from_magnetic(hold.inbound_course_mag_deg, magnetic_variation_deg),
        arrival_course_true_deg,
        hold.turn_direction,
    )


def hold_leg_length_nm(hold: Hold, tas_kt: float, altitude_ft: float) -> float:
    """Length of one straight leg of a published hold, nautical miles.

    Published holds state their leg either as a **distance** (DME holds) or as a
    **time** (everything else), and a time is only a distance once a speed is
    known — which is why this takes a true airspeed rather than reading one off
    the hold.

    Args:
        hold: The published hold.
        tas_kt: True airspeed the leg is flown at, knots. Wind is not modelled:
            in still air the ground speed is the true airspeed, and a real crew
            adjusts the outbound timing for the wind anyway.
        altitude_ft: Altitude the hold is flown at, feet MSL. Used only to pick
            the standard leg time when the source publishes neither a time nor a
            distance: one minute at or below :data:`HOLD_LEG_TIME_ALTITUDE_FT`,
            one and a half above it.

    Returns:
        The leg length in nautical miles. A published distance is returned
        verbatim; a published time becomes ``tas_kt * minutes / 60``.
    """
    if hold.leg_length_nm is not None:
        return hold.leg_length_nm
    minutes = hold.leg_time_min
    if minutes is None:
        minutes = (
            HOLD_LEG_TIME_HIGH_MIN
            if altitude_ft > HOLD_LEG_TIME_ALTITUDE_FT
            else HOLD_LEG_TIME_LOW_MIN
        )
    return tas_kt * minutes / 60.0


def holding_pattern_point(
    fix: GeoPosition,
    inbound_course_true_deg: float,
    placement: HoldPlacement,
    altitude_ft: float,
    leg_length_nm: float,
    width_nm: float,
    turn_direction: TurnDirection = "R",
) -> tuple[GeoPosition, float]:
    """Position and heading for a point on a holding racetrack.

    Geometry is built on the inbound course, with the **fix as origin**. The
    inbound leg runs *back* from the fix along the reciprocal of the inbound
    course; the outbound leg is parallel to it, ``width_nm`` to the holding
    side — the right of the inbound track in a right-hand hold, which is the
    side the aircraft turns towards after crossing the fix.

    The four points, in the order they are flown from the fix:

    * ``"hold_fix"`` — over the fix itself, heading inbound: the moment the
      outbound turn begins.
    * ``"hold_outbound"`` — abeam the fix on the outbound leg, where outbound
      timing starts, heading the reciprocal.
    * ``"hold_outbound_end"`` — the far end of the outbound leg, about to turn
      inbound.
    * ``"hold_inbound"`` — established inbound, one leg length from the fix.

    Args:
        fix: The holding fix.
        inbound_course_true_deg: Course flown *towards* the fix, **true**
            degrees. Convert a published magnetic course with
            :func:`true_from_magnetic` first.
        placement: Which of the four points.
        altitude_ft: Holding altitude, feet MSL. A hold is flown level, so all
            four points share it.
        leg_length_nm: Length of the straight legs, nautical miles — see
            :func:`hold_leg_length_nm`.
        width_nm: Distance between the inbound and outbound legs, nautical
            miles. Twice the turn radius: the 180° turn at each end is a
            half-circle whose diameter is exactly this.
        turn_direction: ``"R"`` for a standard hold, ``"L"`` for a
            non-standard one.

    Returns:
        ``(position, heading_deg)`` — the position at holding altitude and the
        true heading being flown at that point.

    The turns themselves are not positionable: a point mid-turn depends on the
    bank the aircraft happens to be holding, and placing an aeroplane there
    would put it in an attitude the reposition does not command.
    """
    axis = _normalise_bearing(inbound_course_true_deg)
    # "Across" is positive to the right of the inbound track, which is the
    # holding side of a standard right-hand hold.
    side = 1.0 if turn_direction == "R" else -1.0
    reciprocal = _normalise_bearing(axis + 180.0)

    if placement == "hold_fix":
        along_nm, across_nm, heading = 0.0, 0.0, axis
    elif placement == "hold_outbound":
        along_nm, across_nm, heading = 0.0, side * width_nm, reciprocal
    elif placement == "hold_outbound_end":
        along_nm, across_nm, heading = -leg_length_nm, side * width_nm, reciprocal
    elif placement == "hold_inbound":
        along_nm, across_nm, heading = -leg_length_nm, 0.0, axis
    else:  # pragma: no cover - exhaustive over HoldPlacement
        assert_never(placement)

    return _offset(fix, along_nm, across_nm, axis, altitude_ft), _normalise_bearing(heading)


def _hold_altitude_ft(hold: Hold, altitude_ft: float | None) -> float:
    """The altitude to hold at: the caller's, else the published one.

    A published hold states the altitudes it is *protected* between. The lower
    bound is the one to place at, for the same reason
    :attr:`~core.navdata.models.AltitudeConstraint.suggested_ft` picks it: an
    aircraft joining a hold arrives from above and levels at the bottom of the
    window.
    """
    if altitude_ft is not None:
        return altitude_ft
    if hold.min_altitude_ft is not None:
        return hold.min_altitude_ft
    if hold.max_altitude_ft is not None:
        return hold.max_altitude_ft
    raise ValueError(
        f"the hold at {hold.fix.ident} publishes no altitude, so there is none to place at: "
        "pass altitude_ft. Guessing one would put the aircraft at sea level, or in terrain."
    )


def _hold_geometry(
    hold: Hold,
    altitude_ft: float | None,
    ias_kt: float | None,
    category: ApproachCategory,
    leg_length_nm: float | None,
) -> tuple[float, float, float, float]:
    """Resolve a published hold into ``(altitude, ias, leg length, width)``.

    Shared by every hold placement so that the four points of one racetrack are
    guaranteed to be built from the same numbers.
    """
    altitude = _hold_altitude_ft(hold, altitude_ft)
    speed = _constrained_ias_kt(ias_kt, category, max_kt=hold.speed_kt)
    # The airspeed indicator reads low as the air thins, and a turn is flown
    # through the air mass: at 10 000 ft an indicated 210 kt is a true 244 kt,
    # and using the indicated value would shrink the racetrack by 14 %.
    tas_kt = tas_from_ias(speed, altitude)
    leg_nm = hold_leg_length_nm(hold, tas_kt, altitude) if leg_length_nm is None else leg_length_nm
    return altitude, speed, leg_nm, 2.0 * turn_radius_nm(tas_kt)


def hold_placement(
    hold: Hold,
    placement: HoldPlacement = "hold_fix",
    *,
    magnetic_variation_deg: float,
    altitude_ft: float | None = None,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
    leg_length_nm: float | None = None,
) -> Placement:
    """Place the aircraft in a published holding pattern.

    Everything that can be read is read: the fix, the inbound course, the turn
    direction, the leg length or time, the altitude window and the speed
    restriction all come off the published hold. What is computed is only what
    the source does not say — where the racetrack sits on the ground, which
    needs a turn radius, which needs a true airspeed, which needs the altitude.

    Args:
        hold: The published hold, from
            :meth:`core.navdata.provider.NavdataProvider.get_holds`.
        placement: Which of :data:`HOLD_PLACEMENTS` to sit at. The default is
            the fix, the one point of a hold every instructor names.
        magnetic_variation_deg: Local variation, degrees positive east.
            Required: the published inbound course is magnetic and this module
            is true.
        altitude_ft: Holding altitude, feet MSL. ``None`` takes the hold's
            published lower altitude.
        ias_kt: Indicated airspeed to command, knots. ``None`` takes the
            ``category``'s circling speed, clamped by any published speed
            restriction — see :func:`_constrained_ias_kt` for why a placard is
            treated as a ceiling and not as a target.
        category: The aircraft's ICAO approach category, used only when
            ``ias_kt`` is ``None``.
        leg_length_nm: Overrides the leg length, nautical miles. ``None``
            computes it from the published distance or time.

    Returns:
        The :class:`Placement`, level at holding altitude and at a manoeuvring
        speed.

    Raises:
        ValueError: if neither the caller nor the source states an altitude.
    """
    altitude, speed, leg_nm, width_nm = _hold_geometry(
        hold, altitude_ft, ias_kt, category, leg_length_nm
    )
    position, heading_deg = holding_pattern_point(
        hold.fix.position,
        true_from_magnetic(hold.inbound_course_mag_deg, magnetic_variation_deg),
        placement,
        altitude,
        leg_nm,
        width_nm,
        hold.turn_direction,
    )
    return Placement(
        position=position,
        heading_deg=heading_deg,
        ias_kt=speed,
        label=f"{hold.fix.ident} hold — {_HOLD_PLACEMENT_LABELS[placement]}",
        profile="airborne",
    )


def hold_entry_placement(
    hold: Hold,
    arrival_course_true_deg: float,
    *,
    magnetic_variation_deg: float,
    distance_nm: float = DEFAULT_HOLD_ENTRY_DISTANCE_NM,
    altitude_ft: float | None = None,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
) -> Placement:
    """Place the aircraft *approaching* a hold, so the student flies the entry.

    The aircraft is put ``distance_nm`` before the fix on the course it would
    arrive by, level at holding altitude — which is the exercise: recognising
    the sector and flying the direct, parallel or teardrop entry. The entry the
    geometry implies is named in the label, so the instructor briefing and the
    aircraft's position cannot disagree.

    Args:
        hold: The published hold.
        arrival_course_true_deg: Course the aircraft is to be flying when it
            reaches the fix, **true** degrees. This is what selects the entry.
        magnetic_variation_deg: Local variation, degrees positive east.
        distance_nm: How far before the fix to start, nautical miles.
        altitude_ft: Holding altitude, feet MSL. ``None`` takes the hold's
            published lower altitude.
        ias_kt: Indicated airspeed to command, knots. ``None`` behaves as in
            :func:`hold_placement`.
        category: The aircraft's ICAO approach category.

    Returns:
        The :class:`Placement`, tracking the fix. Its heading is the exact
        geodesic course from the placed point *to* the fix, which is not in
        general ``arrival_course_true_deg``: the requested course is the one
        flown **over the fix**, and along the way the true heading swings by the
        convergence of the meridians — 0.04° over 3 NM of easterly track at
        40° latitude, and proportionally more the further from the equator and
        the longer the leg. It is the arrival that is exact, because it is the
        arrival that selects the entry sector. Not a correction anyone flies,
        but no reason to hand back a heading the aircraft is not on.

    Raises:
        ValueError: if neither the caller nor the source states an altitude.
    """
    altitude, speed, _, _ = _hold_geometry(hold, altitude_ft, ias_kt, category, None)
    fix = hold.fix.position
    start = point_at_distance_and_bearing(
        fix, distance_nm, _normalise_bearing(arrival_course_true_deg + 180.0)
    )
    _, course_to_fix = distance_and_bearing(start, fix)
    entry = hold_entry(hold, course_to_fix, magnetic_variation_deg=magnetic_variation_deg)
    return Placement(
        position=GeoPosition(
            latitude=start.latitude, longitude=start.longitude, altitude_ft=altitude
        ),
        heading_deg=course_to_fix,
        ias_kt=speed,
        label=f"{hold.fix.ident} hold — {entry} entry",
        profile="airborne",
    )


# ---------------------------------------------------------------------------
# Published procedures: SIDs, STARs and approaches
# ---------------------------------------------------------------------------


def positionable_legs(procedure: Procedure) -> tuple[ProcedureLeg, ...]:
    """The legs of a procedure that can actually be flown to a coordinate.

    A procedure is displayed whole — an instructor reading a SID needs to see
    the climb leg — but only legs whose path terminator carries a fix, and whose
    fix resolved against the index, have a defensible position. The provider has
    already decided that per leg; this is the filter the UI builds its menu
    from, stated once so that no caller re-derives it from the terminator.
    """
    return tuple(leg for leg in procedure.legs if leg.is_positionable)


def _leg_fix(leg: ProcedureLeg) -> Waypoint:
    """The resolved fix of a positionable leg, or a refusal that says why.

    Placing an aircraft on a leg that carries no coordinate is not a thing this
    module can do approximately: a ``CA`` leg is "climb on this course until an
    altitude", and where that ends depends on the aeroplane, not on the chart.
    Callers gate on :attr:`~core.navdata.models.ProcedureLeg.is_positionable`,
    which the UI already uses to grey the leg out; reaching here without it is a
    programming error and is reported as one.
    """
    if not leg.is_positionable or leg.fix is None:
        reason = leg.unpositionable_reason or (
            f"a {leg.path_terminator} leg carries no fix to position at"
        )
        raise ValueError(
            f"leg {leg.sequence} ({leg.path_terminator}) is not positionable: {reason}"
        )
    return leg.fix


def procedure_leg_placement(
    leg: ProcedureLeg,
    *,
    altitude_ft: float | None = None,
    heading_deg: float | None = None,
    next_fix: GeoPosition | Waypoint | None = None,
    previous_fix: GeoPosition | Waypoint | None = None,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
    procedure_ident: str | None = None,
) -> Placement:
    """Place the aircraft on a leg of a published procedure.

    The leg supplies the position and, where the chart states them, the altitude
    and the speed. It cannot supply a heading: an ARINC leg publishes its
    outbound course in **magnetic** degrees, and converting that needs a
    magnetic model this project does not carry — so the heading comes from the
    surrounding geometry (the bearing to the next fix, or the course the
    previous leg arrives on), or from the caller.

    Args:
        leg: The leg to place at. Must be positionable.
        altitude_ft: Target altitude, feet MSL. ``None`` takes the leg's
            published altitude constraint, resolved by
            :attr:`~core.navdata.models.AltitudeConstraint.suggested_ft`.
        heading_deg: Explicit true heading, degrees.
        next_fix: The fix the aircraft would fly to next.
        previous_fix: The fix the aircraft would be coming from.
        ias_kt: Indicated airspeed to command, knots. ``None`` takes the
            ``category``'s circling speed folded into the leg's published speed
            band.
        category: The aircraft's ICAO approach category.
        procedure_ident: The procedure's name, used only for the label.

    Returns:
        The :class:`Placement` over the leg's fix.

    Raises:
        ValueError: if the leg is not positionable, or if neither the caller nor
            the chart states an altitude — a leg with no published constraint is
            common (that is what "unrestricted" means) and there is nothing to
            infer from it.
    """
    fix = _leg_fix(leg)
    altitude = altitude_ft if altitude_ft is not None else _published_altitude_ft(leg)
    if altitude is None:
        raise ValueError(
            f"leg {leg.sequence} at {fix.ident} publishes no altitude constraint, so there is "
            "none to place at: pass altitude_ft."
        )
    speed = _constrained_ias_kt(
        ias_kt,
        category,
        min_kt=leg.speed.min_kt if leg.speed is not None else None,
        max_kt=leg.speed.max_kt if leg.speed is not None else None,
    )
    return Placement(
        position=GeoPosition(
            latitude=fix.position.latitude,
            longitude=fix.position.longitude,
            altitude_ft=altitude,
        ),
        heading_deg=_contextual_heading_deg(fix.position, heading_deg, next_fix, previous_fix),
        ias_kt=speed,
        label=_leg_label(leg, fix, procedure_ident),
        profile="airborne",
    )


def _published_altitude_ft(leg: ProcedureLeg) -> float | None:
    """The leg's own altitude, when the chart states one."""
    return None if leg.altitude is None else leg.altitude.suggested_ft


def _leg_label(leg: ProcedureLeg, fix: Waypoint, procedure_ident: str | None) -> str:
    """``"I32L at ELVAR (FAF)"`` — the procedure, the fix, and the fix's role."""
    role = ""
    if leg.is_final_approach_fix:
        role = " (FAF)"
    elif leg.is_initial_approach_fix:
        role = " (IAF)"
    elif leg.is_missed_approach_point:
        role = " (MAP)"
    if procedure_ident is None:
        return f"over {fix.ident}{role}"
    return f"{procedure_ident} at {fix.ident}{role}"


def procedure_placement(
    procedure: Procedure,
    sequence: int,
    *,
    altitude_ft: float | None = None,
    heading_deg: float | None = None,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
) -> Placement:
    """Place the aircraft at one leg of a SID, STAR or approach, by sequence.

    The single entry point the API layer needs: it holds a procedure and a leg
    number, and everything else — which fixes surround that leg, and therefore
    which way the aircraft should be pointing — is read off the procedure rather
    than assembled by the caller. Unpositionable legs are skipped when looking
    for the neighbours, so a fix on the far side of a climb leg still orients
    the aircraft.

    Args:
        procedure: The procedure, with its legs resolved.
        sequence: The leg's published sequence number (10, 20, 30 …), not its
            index in the list.
        altitude_ft: Target altitude, feet MSL, or ``None`` for the leg's own
            constraint.
        heading_deg: Explicit true heading, degrees, overriding the geometry.
        ias_kt: Indicated airspeed to command, knots.
        category: The aircraft's ICAO approach category.

    Returns:
        The :class:`Placement` over that leg's fix, labelled with the procedure.

    Raises:
        ValueError: if no leg carries that sequence number, if the leg is not
            positionable, or if no altitude can be determined.
    """
    legs = procedure.legs
    index = next((i for i, leg in enumerate(legs) if leg.sequence == sequence), None)
    if index is None:
        published = ", ".join(str(leg.sequence) for leg in legs) or "none"
        raise ValueError(
            f"{procedure.ident} has no leg with sequence {sequence}; it publishes {published}."
        )
    return procedure_leg_placement(
        legs[index],
        altitude_ft=altitude_ft,
        heading_deg=heading_deg,
        next_fix=_nearest_fix(legs[index + 1 :]),
        previous_fix=_nearest_fix(reversed(legs[:index])),
        ias_kt=ias_kt,
        category=category,
        procedure_ident=_procedure_ident(procedure),
    )


def _nearest_fix(legs: Iterable[ProcedureLeg]) -> Waypoint | None:
    """The first resolved fix in a run of legs, walking away from the placement."""
    return next((leg.fix for leg in legs if leg.fix is not None), None)


def _procedure_ident(procedure: Procedure) -> str:
    """``"BARD3B"``, or ``"BARD3B.ADUXO"`` when a transition names one route of it."""
    if procedure.transition is None:
        return procedure.ident
    return f"{procedure.ident}.{procedure.transition}"
