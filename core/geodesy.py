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
altitude, pointing *which* way. :data:`RUNWAY_PLACEMENTS` is the whole
catalogue and :func:`resolve_runway_placement` is the single entry point, so an
API layer enumerates and dispatches without knowing any geometry.
:func:`coordinate_placement` and :func:`waypoint_placement` cover the two
placements that need no runway.

Holding entries and procedure (SID/STAR/approach) legs are deliberately absent:
both resolve against published navdata — ``earth_hold.dat`` and the CIFP — and
inventing their geometry here instead of reading the published values would be
wrong.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, assert_never

from geographiclib.geodesic import Geodesic
from pydantic import BaseModel, ConfigDict, Field

from core.models import GeoPosition, Runway

__all__ = [
    "DEFAULT_GLIDESLOPE_DEG",
    "DEFAULT_PATTERN_ALTITUDE_AGL_FT",
    "DEFAULT_PATTERN_LEG_DISTANCE_NM",
    "DEFAULT_PATTERN_WIDTH_NM",
    "FEET_PER_NAUTICAL_MILE",
    "FINAL_DISTANCES_NM",
    "METRES_PER_NAUTICAL_MILE",
    "PATTERN_PLACEMENTS",
    "RUNWAY_PLACEMENTS",
    "SHORT_FINAL_DISTANCE_NM",
    "FinalPlacement",
    "PatternLeg",
    "PatternPlacement",
    "PatternSide",
    "Placement",
    "RunwayPlacement",
    "coordinate_placement",
    "distance_and_bearing",
    "final_approach_point",
    "final_placement",
    "glideslope_altitude_ft",
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
    """A resolved placement: where to put the aircraft and which way to face it.

    Everything an instructor station needs to reposition, and nothing about how
    the repositioning happens — building the aircraft state around it is the
    Position Manager's job, writing it is the adapter's.
    """

    model_config = ConfigDict(frozen=True)

    position: GeoPosition = Field(
        description="Target position; its altitude_ft is the target altitude, feet MSL."
    )
    heading_deg: float = Field(
        ge=0.0, lt=360.0, description="True heading to fly at that point, degrees."
    )
    label: str = Field(
        min_length=1,
        description='Human-readable description, e.g. "LEMD 32L 10 NM final".',
    )

    @property
    def altitude_ft(self) -> float:
        """Target altitude in feet MSL — the same value as ``position.altitude_ft``."""
        return self.position.altitude_ft


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


def final_placement(
    runway: Runway,
    placement: FinalPlacement,
    *,
    glideslope_deg: float = DEFAULT_GLIDESLOPE_DEG,
) -> Placement:
    """Place the aircraft on a named final, on the glidepath.

    Args:
        runway: The runway being approached.
        placement: Which named final — see :data:`FINAL_DISTANCES_NM` for the
            distance out, in nautical miles, that each name resolves to.
        glideslope_deg: Glidepath angle in degrees.

    Returns:
        A :class:`Placement` on the extended centreline at the glidepath
        altitude for that distance (feet MSL), heading down the runway
        centreline in true degrees.
    """
    distance_nm = FINAL_DISTANCES_NM[placement]
    what = "short final" if placement == "short_final" else f"{distance_nm:g} NM final"
    return Placement(
        position=final_approach_point(runway, distance_nm, glideslope_deg),
        heading_deg=_normalise_bearing(runway.true_bearing_deg),
        label=_runway_label(runway, what),
    )


def pattern_placement(
    runway: Runway,
    placement: PatternPlacement,
    *,
    pattern_altitude_ft: float | None = None,
    pattern_width_nm: float = DEFAULT_PATTERN_WIDTH_NM,
    leg_distance_nm: float = DEFAULT_PATTERN_LEG_DISTANCE_NM,
) -> Placement:
    """Place the aircraft on a named circuit leg.

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

    Returns:
        A :class:`Placement` at pattern altitude, heading down that leg. The
        right-hand pattern is the mirror image of the left-hand one about the
        runway centreline.
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

    Returns:
        The resolved :class:`Placement`.
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
            return final_placement(runway, placement, glideslope_deg=glideslope_deg)
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
            )
        case _:  # pragma: no cover - exhaustive over RunwayPlacement
            assert_never(placement)


def coordinate_placement(position: GeoPosition, heading_deg: float = 0.0) -> Placement:
    """Place the aircraft at an arbitrary coordinate.

    Args:
        position: Where to put it. ``altitude_ft`` is the target altitude,
            feet MSL.
        heading_deg: True heading in degrees; folded into ``[0, 360)``.

    Returns:
        The placement, verbatim — nothing about a free coordinate is derived.
    """
    return Placement(
        position=position,
        heading_deg=_normalise_bearing(heading_deg),
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

    Returns:
        The placement over the waypoint at ``altitude_ft``.
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
        label=f"over {ident}",
    )
