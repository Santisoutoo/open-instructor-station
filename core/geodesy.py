"""WGS84 geodesy primitives.

Pure functions over :mod:`core.models` — no simulator, no I/O, no global state.
All distances taken and returned by the public API are **nautical miles**, all
bearings and headings are **true degrees** normalised to ``[0, 360)``, and all
altitudes are **feet MSL**. Internally everything runs through
:mod:`geographiclib` on the WGS84 ellipsoid, whose native unit is the metre.
"""

from __future__ import annotations

import math
from typing import Literal, assert_never

from geographiclib.geodesic import Geodesic

from core.models import GeoPosition, Runway

__all__ = [
    "FEET_PER_NAUTICAL_MILE",
    "METRES_PER_NAUTICAL_MILE",
    "PatternLeg",
    "distance_and_bearing",
    "final_approach_point",
    "glideslope_altitude_ft",
    "point_at_distance_and_bearing",
    "traffic_pattern_point",
]

#: Exact conversion: 1 international nautical mile = 1852 m = 1852 / 0.3048 ft.
METRES_PER_NAUTICAL_MILE: float = 1852.0
FEET_PER_NAUTICAL_MILE: float = METRES_PER_NAUTICAL_MILE / 0.3048  # 6076.115485564304

#: Legs of a standard rectangular traffic pattern.
PatternLeg = Literal["downwind", "base", "crosswind", "upwind"]

_WGS84: Geodesic = Geodesic.WGS84


def _normalise_bearing(bearing_deg: float) -> float:
    """Fold any angle in degrees into ``[0, 360)``."""
    return bearing_deg % 360.0


def point_at_distance_and_bearing(
    origin: GeoPosition,
    distance_nm: float,
    bearing_deg: float,
) -> GeoPosition:
    """Solve the direct geodesic problem.

    Args:
        origin: Starting point. Its ``altitude_ft`` is carried over unchanged.
        distance_nm: Geodesic distance to travel, in nautical miles.
        bearing_deg: Initial true bearing in degrees.

    Returns:
        The destination point, at the same altitude as ``origin``.
    """
    result = _WGS84.Direct(
        origin.latitude,
        origin.longitude,
        _normalise_bearing(bearing_deg),
        distance_nm * METRES_PER_NAUTICAL_MILE,
    )
    return GeoPosition(
        latitude=float(result["lat2"]),
        longitude=float(result["lon2"]),
        altitude_ft=origin.altitude_ft,
    )


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
    glideslope_deg: float = 3.0,
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
    glideslope_deg: float = 3.0,
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
    """
    axis = _normalise_bearing(axis_bearing_deg)
    moved = point_at_distance_and_bearing(origin, along_nm, axis)
    if across_nm != 0.0:
        perpendicular = axis + 90.0 * math.copysign(1.0, across_nm)
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
    pattern_width_nm: float = 1.0,
    leg_distance_nm: float = 1.5,
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
