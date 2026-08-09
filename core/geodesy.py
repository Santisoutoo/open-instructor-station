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

**Placements.** Every runway-relative position the Position Manager offers has a
name — ``"final_10nm"``, ``"left_downwind"``, ``"short_final"`` — and resolving
one yields a :class:`Placement`: *where* to put the aircraft, at *what*
altitude, pointing *which* way and at *what speed*. :data:`RUNWAY_PLACEMENTS` is
the whole catalogue and :func:`resolve_runway_placement` is the single entry
point, so an API layer enumerates and dispatches without knowing any geometry.
:func:`coordinate_placement` and :func:`waypoint_placement` cover the two
placements that need no runway.

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

Procedure (SID/STAR/approach) legs are deliberately absent: they resolve against
published navdata — the CIFP — and inventing their geometry here instead of
reading the published values would be wrong. Holds follow the same rule but do
have geometry of their own: :func:`hold_placement` takes the published pattern
(inbound course, turn direction, leg length) as *input* and only answers the
question the published data does not, which is which entry the aircraft is set
up for. It invents nothing.

**Everything in this module is true, never magnetic.** ``earth_hold.dat`` and
the CIFP publish courses in magnetic degrees, and converting needs a world
magnetic model this project deliberately does not carry (see
:mod:`core.navdata.models`). Callers convert before they get here, and say in
the UI that they did.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, assert_never

from geographiclib.geodesic import Geodesic
from pydantic import BaseModel, ConfigDict, Field

from core.models import AircraftSetup, GeoPosition, Runway

__all__ = [
    "APPROACH_CATEGORY_CIRCLING_IAS_KT",
    "APPROACH_CATEGORY_VAT_KT",
    "DEFAULT_APPROACH_CATEGORY",
    "DEFAULT_GLIDESLOPE_DEG",
    "DEFAULT_PATTERN_ALTITUDE_AGL_FT",
    "DEFAULT_PATTERN_LEG_DISTANCE_NM",
    "DEFAULT_PATTERN_WIDTH_NM",
    "FEET_PER_NAUTICAL_MILE",
    "FINAL_DISTANCES_NM",
    "GROUND_IAS_KT",
    "METRES_PER_NAUTICAL_MILE",
    "PARALLEL_SECTOR_DEG",
    "PATTERN_PLACEMENTS",
    "RUNWAY_PLACEMENTS",
    "SHORT_FINAL_DISTANCE_NM",
    "TEARDROP_SECTOR_DEG",
    "ApproachCategory",
    "FinalPlacement",
    "HoldEntry",
    "PatternLeg",
    "PatternPlacement",
    "PatternSide",
    "Placement",
    "RunwayPlacement",
    "TurnDirection",
    "coordinate_placement",
    "distance_and_bearing",
    "final_approach_point",
    "final_placement",
    "glideslope_altitude_ft",
    "hold_entry",
    "hold_leg_length_nm",
    "hold_placement",
    "pattern_placement",
    "point_at_distance_and_bearing",
    "resolve_runway_placement",
    "traffic_pattern_point",
    "waypoint_placement",
]

#: Exact conversion: 1 international nautical mile = 1852 m = 1852 / 0.3048 ft.
METRES_PER_NAUTICAL_MILE: float = 1852.0
FEET_PER_NAUTICAL_MILE: float = METRES_PER_NAUTICAL_MILE / 0.3048  # 6076.115485564304

#: Legs of a standard rectangular traffic pattern.
PatternLeg = Literal["downwind", "base", "crosswind", "upwind"]

#: Which side of the runway the pattern is flown on.
PatternSide = Literal["left", "right"]

#: Direction of turn in a holding pattern, spelled the way ``earth_hold.dat``
#: and the CIFP spell it. ``"R"`` is the standard (right-hand) pattern.
TurnDirection = Literal["L", "R"]

#: The three published holding entries (ICAO Doc 8168).
HoldEntry = Literal["direct", "parallel", "teardrop"]

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


class Placement(BaseModel):
    """A resolved placement: where to put the aircraft, facing where, doing what speed.

    Everything an instructor station needs to reposition, and nothing about how
    the repositioning happens — writing it is the adapter's job.

    ``ias_kt`` has **no default on purpose**. It is the one field of this model
    that cannot be inferred from geometry, and leaving it out is precisely the
    defect that put an aircraft on a perfect 10 NM final at 0 kt, so a new
    placement type cannot be written without answering the question.
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

    @property
    def altitude_ft(self) -> float:
        """Target altitude in feet MSL — the same value as ``position.altitude_ft``."""
        return self.position.altitude_ft

    def to_setup(self) -> AircraftSetup:
        """The aircraft state to apply **before** the reposition is written.

        Only the three fields the geometry of a placement actually determines
        are set — altitude, heading and speed. Every other field is left
        ``None``, which an adapter reads as *leave that aspect untouched*.

        The remaining thirteen fields of :class:`~core.models.AircraftSetup` —
        mass, flaps, gear, spoilers, autobrake, lights, radios — are the full
        pre-teleport setup, and they depend on the placement *profile* (a short
        final is not configured like a 20 NM one) rather than on where the point
        is. That is issue #8's, and it extends this method rather than replacing
        it.
        """
        return AircraftSetup(
            altitude_ft=self.position.altitude_ft,
            heading_deg=self.heading_deg,
            ias_kt=self.ias_kt,
        )


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

    Args:
        runway: The target runway end.
        distance_nm: Distance out from the threshold, nautical miles.
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

    Geometry is built on the runway axis, with the threshold as origin. The
    pattern lies on the left of the runway when ``left_hand`` is true (all
    turns to the left), on the right otherwise.

    Args:
        runway: The runway the pattern is flown around.
        leg: Which leg to position on.
        pattern_altitude_ft: Pattern altitude, feet MSL.
        pattern_width_nm: Lateral distance from the centreline to the downwind
            leg, in nautical miles.
        leg_distance_nm: How far beyond the departure end the upwind/crosswind
            legs sit, and how far before the threshold the base leg sits, in
            nautical miles.
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


def final_placement(
    runway: Runway,
    placement: FinalPlacement,
    *,
    glideslope_deg: float = DEFAULT_GLIDESLOPE_DEG,
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
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
    """
    return Placement(
        position=position,
        heading_deg=_normalise_bearing(heading_deg),
        ias_kt=ias_kt,
        label=f"{position.latitude:.4f}, {position.longitude:.4f}",
    )


def waypoint_placement(
    waypoint: GeoPosition,
    altitude_ft: float,
    *,
    ident: str = "waypoint",
    heading_deg: float | None = None,
    next_fix: GeoPosition | None = None,
    previous_fix: GeoPosition | None = None,
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
        waypoint: The fix to sit over. Its own ``altitude_ft`` is ignored in
            favour of ``altitude_ft``, because navdata fixes carry no altitude.
        altitude_ft: Target altitude, feet MSL.
        ident: Fix name, used only for the label.
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
    if heading_deg is not None:
        heading = _normalise_bearing(heading_deg)
    elif next_fix is not None:
        _, heading = distance_and_bearing(waypoint, next_fix)
    elif previous_fix is not None:
        heading = _arrival_bearing(previous_fix, waypoint)
    else:
        heading = 0.0
    return Placement(
        position=GeoPosition(
            latitude=waypoint.latitude,
            longitude=waypoint.longitude,
            altitude_ft=altitude_ft,
        ),
        heading_deg=heading,
        ias_kt=_resolve_ias_kt(ias_kt, APPROACH_CATEGORY_CIRCLING_IAS_KT, category),
        label=f"over {ident}",
    )


# ---------------------------------------------------------------------------
# Holding patterns
# ---------------------------------------------------------------------------

#: Width of the teardrop (offset) entry sector, degrees. ICAO Doc 8168.
TEARDROP_SECTOR_DEG: float = 70.0

#: Width of the parallel entry sector, degrees.
PARALLEL_SECTOR_DEG: float = 110.0


def hold_entry(
    inbound_course_deg: float,
    arrival_heading_deg: float,
    turn_direction: TurnDirection = "R",
) -> HoldEntry:
    """Which published entry an aircraft arriving on ``arrival_heading_deg`` flies.

    The three sectors of ICAO Doc 8168, measured about the fix and expressed
    relative to the inbound course: a 180° direct sector, a 70° teardrop sector
    and a 110° parallel sector. A left-hand hold is the exact mirror of a
    right-hand one, and is computed as such rather than written out twice — the
    two tables would drift apart the first time one of them was corrected.

    Args:
        inbound_course_deg: Course flown **to** the fix on the inbound leg,
            TRUE degrees.
        arrival_heading_deg: The aircraft's true heading as it reaches the fix.
        turn_direction: ``"R"`` for the standard right-hand pattern.

    Returns:
        The entry the aircraft is set up for. A heading exactly on a sector
        boundary resolves deterministically; in the air either neighbouring
        entry is acceptable there, so the boundary case is a convention rather
        than a fact.
    """
    relative = _normalise_bearing(arrival_heading_deg - inbound_course_deg)
    if turn_direction == "L":
        relative = _normalise_bearing(-relative)
    if PARALLEL_SECTOR_DEG < relative <= 180.0:
        return "teardrop"
    if 180.0 < relative < 360.0 - TEARDROP_SECTOR_DEG:
        return "parallel"
    return "direct"


def hold_leg_length_nm(
    ias_kt: float,
    *,
    leg_length_nm: float | None = None,
    leg_time_min: float | None = None,
) -> float | None:
    """Length of the hold's outbound leg, whichever way it was published.

    ``earth_hold.dat`` publishes exactly one of the two — a distance or a time —
    and a time is only a length once a speed is chosen. Returns ``None`` when
    neither was published, rather than inventing the ICAO one-minute default:
    the caller is drawing a diagram with it, and a guessed racetrack drawn as
    confidently as a published one is a lie the instructor cannot see through.
    """
    if leg_length_nm is not None:
        return leg_length_nm
    if leg_time_min is not None:
        return ias_kt * leg_time_min / 60.0
    return None


def hold_placement(
    fix: GeoPosition,
    inbound_course_deg: float,
    turn_direction: TurnDirection,
    altitude_ft: float,
    *,
    ident: str = "hold",
    ias_kt: float | None = None,
    category: ApproachCategory = DEFAULT_APPROACH_CATEGORY,
) -> Placement:
    """Place the aircraft in a published hold, over the fix, on the inbound course.

    **Over the fix, not somewhere on the racetrack.** A hold is a pattern rather
    than a point, so "put the aircraft in the hold" has no single answer — but
    the holding fix on the inbound course is the one an instructor means and the
    one every entry converges on. Placing part-way round the pattern would put
    the aircraft somewhere the student cannot identify on a chart.

    Args:
        fix: The holding fix. Its own ``altitude_ft`` is ignored in favour of
            ``altitude_ft``, because navdata fixes carry no altitude.
        inbound_course_deg: Course flown to the fix, **TRUE** degrees. The
            published value is magnetic; converting it is the caller's job and
            this module has no magnetic model — see the module docstring.
        turn_direction: ``"R"`` for the standard right-hand pattern.
        altitude_ft: Target altitude, feet MSL. Callers should pass the hold's
            published minimum when there is one.
        ident: Fix name, used only for the label.
        ias_kt: Indicated airspeed to command, knots. ``None`` takes the
            ``category``'s circling speed, used here as a generic manoeuvring
            speed. A hold is always flown, so a speed is defaulted rather than
            withheld.
        category: The aircraft's ICAO approach category, used only when
            ``ias_kt`` is ``None``.

    Returns:
        The placement over the fix, established inbound, flying.
    """
    return Placement(
        position=GeoPosition(
            latitude=fix.latitude,
            longitude=fix.longitude,
            altitude_ft=altitude_ft,
        ),
        heading_deg=_normalise_bearing(inbound_course_deg),
        ias_kt=_resolve_ias_kt(ias_kt, APPROACH_CATEGORY_CIRCLING_IAS_KT, category),
        label=f"{ident} hold, {'right' if turn_direction == 'R' else 'left'}-hand",
    )
