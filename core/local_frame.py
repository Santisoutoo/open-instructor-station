"""Conversion between WGS84 world coordinates and a local Cartesian frame.

Pure functions over :mod:`core.models` — no simulator, no I/O, no global state,
and no knowledge of how any particular simulator names things.

Flight simulators do not store the aircraft's position as latitude/longitude.
They store it in a **local Cartesian frame**: a right-handed metric system whose
origin sits on the WGS84 ellipsoid at some reference latitude/longitude, with

===== ==================================================
``x`` metres **east** of the origin
``y`` metres **up**, along the ellipsoid normal at the origin
``z`` metres **south** of the origin
===== ==================================================

Latitude/longitude/elevation are *derived* from that frame, which is why moving
an aircraft means writing the local coordinates. This module is the conversion,
and nothing here knows that X-Plane is the caller.

**This is a rigid ECEF rotation, not a flat-earth offset.** The distinction is
not academic: the origin can be tens of kilometres away, and a point 40 km out
sits ~120 m *below* the origin's tangent plane. Ignoring that term is the
difference between a teleport arriving at the requested altitude and one
arriving inside a hill. :mod:`geographiclib` exposes no geocentric transform —
only geodesics on the surface — so the ellipsoid maths is spelled out here; the
geodesic solver is still used for the search in :func:`origin_from_observation`.

**A local frame is not permanent.** Simulators relocate the anchor to keep the
coordinates small — X-Plane does it during a scenery reload — and the same
``(x, y, z)`` triple then denotes a different place on earth. Nothing here
caches an origin, and :func:`origin_separation_m` exists so that a caller
holding two measurements can tell "the same frame, measured twice" from "the
frame moved".

Units follow the rest of ``core``: everything crossing the public API as a
:class:`~core.models.GeoPosition` carries **feet MSL**, while the local frame is
metres, because metres are the frame's own unit and converting it would only
invite mistakes.
"""

from __future__ import annotations

import math

from geographiclib.geodesic import Geodesic
from pydantic import BaseModel, ConfigDict, Field

from core.models import GeoPosition

__all__ = [
    "LocalCoordinates",
    "LocalFrameOrigin",
    "local_to_world",
    "origin_from_observation",
    "origin_separation_m",
    "world_to_local",
]

_METRES_PER_FOOT = 0.3048

# WGS84 defining parameters. Same ellipsoid geographiclib runs on, so the two
# halves of core's geodesy agree to the last significant figure.
_SEMI_MAJOR_AXIS_M = 6_378_137.0
_FLATTENING = 1.0 / 298.257223563
_ECCENTRICITY_SQ = _FLATTENING * (2.0 - _FLATTENING)

_WGS84: Geodesic = Geodesic.WGS84

#: Iterations used to invert the geodetic↔geocentric relation and to search for
#: a frame origin. Both converge quadratically; these counts leave a wide margin
#: over the ~4 rounds each actually needs.
_ECEF_TO_GEODETIC_ITERATIONS = 6
_ORIGIN_SEARCH_ITERATIONS = 12

_Vector3 = tuple[float, float, float]


class LocalCoordinates(BaseModel):
    """A point in a local Cartesian frame, in metres.

    Axes are ``+x`` east, ``+y`` up and ``+z`` south of the frame origin.
    """

    model_config = ConfigDict(frozen=True)

    x_m: float = Field(description="Metres east of the frame origin.")
    y_m: float = Field(description="Metres up from the frame origin.")
    z_m: float = Field(description="Metres south of the frame origin.")


class LocalFrameOrigin(BaseModel):
    """Where a local Cartesian frame is anchored on the WGS84 ellipsoid.

    ``latitude``/``longitude`` fix both the origin and the orientation of the
    axes, which follow the ellipsoid normal *at that point*.
    """

    model_config = ConfigDict(frozen=True)

    latitude: float = Field(ge=-90.0, le=90.0, description="Degrees, WGS84, positive north.")
    longitude: float = Field(ge=-180.0, le=180.0, description="Degrees, WGS84, positive east.")
    vertical_offset_m: float = Field(
        default=0.0,
        description=(
            "Metres added to the computed up-axis value. Absorbs the small "
            "constant disagreement between a simulator's vertical datum and "
            "height above the WGS84 ellipsoid."
        ),
    )


def _to_ecef(latitude: float, longitude: float, height_m: float) -> _Vector3:
    """Geodetic coordinates to earth-centred, earth-fixed metres."""
    lat = math.radians(latitude)
    lon = math.radians(longitude)
    sin_lat = math.sin(lat)
    prime_vertical = _SEMI_MAJOR_AXIS_M / math.sqrt(1.0 - _ECCENTRICITY_SQ * sin_lat * sin_lat)
    return (
        (prime_vertical + height_m) * math.cos(lat) * math.cos(lon),
        (prime_vertical + height_m) * math.cos(lat) * math.sin(lon),
        (prime_vertical * (1.0 - _ECCENTRICITY_SQ) + height_m) * sin_lat,
    )


def _from_ecef(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Earth-centred, earth-fixed metres back to ``(latitude, longitude, height_m)``.

    Bowring's iteration. It converges on anything short of the earth's centre,
    which no aircraft position reaches.
    """
    longitude = math.atan2(y, x)
    equatorial_distance = math.hypot(x, y)
    latitude = math.atan2(z, equatorial_distance * (1.0 - _ECCENTRICITY_SQ))
    prime_vertical = _SEMI_MAJOR_AXIS_M
    height_m = 0.0
    for _ in range(_ECEF_TO_GEODETIC_ITERATIONS):
        sin_lat = math.sin(latitude)
        prime_vertical = _SEMI_MAJOR_AXIS_M / math.sqrt(1.0 - _ECCENTRICITY_SQ * sin_lat * sin_lat)
        height_m = equatorial_distance / math.cos(latitude) - prime_vertical
        latitude = math.atan2(
            z,
            equatorial_distance
            * (1.0 - _ECCENTRICITY_SQ * prime_vertical / (prime_vertical + height_m)),
        )
    sin_lat = math.sin(latitude)
    prime_vertical = _SEMI_MAJOR_AXIS_M / math.sqrt(1.0 - _ECCENTRICITY_SQ * sin_lat * sin_lat)
    height_m = equatorial_distance / math.cos(latitude) - prime_vertical
    return math.degrees(latitude), math.degrees(longitude), height_m


def _enu_basis(latitude: float, longitude: float) -> tuple[_Vector3, _Vector3, _Vector3]:
    """East, up and north unit vectors at a point, expressed in ECEF axes."""
    lat = math.radians(latitude)
    lon = math.radians(longitude)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    east = (-sin_lon, cos_lon, 0.0)
    up = (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat)
    north = (-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat)
    return east, up, north


def _dot(a: _Vector3, b: _Vector3) -> float:
    """Dot product of two 3-vectors."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def world_to_local(origin: LocalFrameOrigin, position: GeoPosition) -> LocalCoordinates:
    """Project a world position into a local Cartesian frame.

    Args:
        origin: The frame's anchor point and vertical datum.
        position: The point to convert. ``altitude_ft`` is feet MSL.

    Returns:
        The position in metres east / up / south of ``origin``.
    """
    origin_ecef = _to_ecef(origin.latitude, origin.longitude, 0.0)
    point_ecef = _to_ecef(
        position.latitude,
        position.longitude,
        position.altitude_ft * _METRES_PER_FOOT,
    )
    delta: _Vector3 = (
        point_ecef[0] - origin_ecef[0],
        point_ecef[1] - origin_ecef[1],
        point_ecef[2] - origin_ecef[2],
    )
    east, up, north = _enu_basis(origin.latitude, origin.longitude)
    return LocalCoordinates(
        x_m=_dot(east, delta),
        y_m=_dot(up, delta) + origin.vertical_offset_m,
        z_m=-_dot(north, delta),
    )


def local_to_world(origin: LocalFrameOrigin, local: LocalCoordinates) -> GeoPosition:
    """Recover a world position from local Cartesian coordinates.

    The exact inverse of :func:`world_to_local`.

    Args:
        origin: The frame's anchor point and vertical datum.
        local: Metres east / up / south of ``origin``.

    Returns:
        The world position, ``altitude_ft`` in feet MSL.
    """
    origin_ecef = _to_ecef(origin.latitude, origin.longitude, 0.0)
    east, up, north = _enu_basis(origin.latitude, origin.longitude)
    height_component = local.y_m - origin.vertical_offset_m
    point_ecef = tuple(
        origin_ecef[axis]
        + east[axis] * local.x_m
        + up[axis] * height_component
        - north[axis] * local.z_m
        for axis in range(3)
    )
    latitude, longitude, height_m = _from_ecef(*point_ecef)
    return GeoPosition(
        latitude=latitude,
        longitude=longitude,
        altitude_ft=height_m / _METRES_PER_FOOT,
    )


def origin_from_observation(
    position: GeoPosition,
    local: LocalCoordinates,
) -> LocalFrameOrigin:
    """Recover a frame's origin from one point known in both coordinate systems.

    A simulator reports the aircraft's world position *and* its local
    coordinates. That single pair pins the frame down completely, which makes
    the conversion self-calibrating: no need to trust a reference-point value
    the simulator advertises separately, and no need for it to be correct.

    The search walks the candidate origin along a geodesic by the residual it
    produces, which converges in a handful of rounds from a starting guess as
    crude as "the origin is right under the aircraft".

    Args:
        position: The point's world position, ``altitude_ft`` in feet MSL.
        local: The same point's coordinates in the frame being identified.

    Returns:
        The frame origin that maps ``position`` onto ``local``, including the
        vertical offset needed to reproduce ``local.y_m`` exactly.
    """
    latitude, longitude = position.latitude, position.longitude
    for _ in range(_ORIGIN_SEARCH_ITERATIONS):
        candidate = LocalFrameOrigin(latitude=latitude, longitude=longitude)
        projected = world_to_local(candidate, position)
        east_error = projected.x_m - local.x_m
        south_error = projected.z_m - local.z_m
        residual_m = math.hypot(east_error, south_error)
        if residual_m < 1e-6:
            break
        # The point landed ``east_error`` too far east, so the origin is that
        # far too far west: step the origin by the error itself.
        step = _WGS84.Direct(
            latitude,
            longitude,
            math.degrees(math.atan2(east_error, -south_error)),
            residual_m,
        )
        latitude, longitude = float(step["lat2"]), float(step["lon2"])

    settled = LocalFrameOrigin(latitude=latitude, longitude=longitude)
    return LocalFrameOrigin(
        latitude=latitude,
        longitude=longitude,
        vertical_offset_m=local.y_m - world_to_local(settled, position).y_m,
    )


def origin_separation_m(first: LocalFrameOrigin, second: LocalFrameOrigin) -> float:
    """How far apart two local frames are anchored, in metres.

    The question this answers is "is this the same frame I measured a moment
    ago, or has it moved?". Two measurements of an unmoved frame taken off a
    stationary aircraft agree to millimetres; a simulator relocating its frame
    moves the anchor by kilometres. Six orders of magnitude separate the two
    cases, so no caller has to tune the threshold it compares against.

    The vertical datum is part of the answer: an origin that kept its anchor but
    changed its vertical offset describes a different frame, and treating the
    two as equal would put an aircraft at the wrong altitude.

    The horizontal term is the straight-line chord through the ellipsoid rather
    than the distance over its surface. The two differ by ~0.1 % at 100 km,
    which is far below any threshold worth setting on this and avoids dragging a
    geodesic solve into what is a comparison.

    Args:
        first: One frame origin.
        second: The other.

    Returns:
        The distance between the two anchors in metres, vertical datum included.
    """
    first_ecef = _to_ecef(first.latitude, first.longitude, 0.0)
    second_ecef = _to_ecef(second.latitude, second.longitude, 0.0)
    horizontal_m = math.dist(first_ecef, second_ecef)
    vertical_m = second.vertical_offset_m - first.vertical_offset_m
    return math.hypot(horizontal_m, vertical_m)
