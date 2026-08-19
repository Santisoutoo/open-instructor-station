"""Resolving an aircraft-relative camera offset against live state, and back.

Per ``docs/designs/camera-manager.md`` §6 (D4/D5).

A saved camera position is stored as an offset from the aircraft — forward,
right, up, plus a look-direction offset — never as a world coordinate (D4).
Recalling one therefore resolves it *fresh* against wherever the aircraft is
right now, which is what keeps "a three-quarter view from the left" the same
view between sessions instead of pointing at a fixed patch of sky. That is the
same re-resolve-at-write-time posture ``core.pushback.pushback_target`` uses.

Two conventions are mixed on purpose (D5), because either axis could
defensibly go the other way:

* ``look_offset_deg`` is **aircraft-heading-relative** — "look left/right" is
  naturally relative to which way the nose points;
* ``pitch_deg`` is **world-frame** — an instructor's "look up/down" is
  independent of the aircraft's own pitch attitude, so it passes through
  untouched.

No simulator, no adapter, no dataref: this module only knows
:class:`~core.models.AircraftState` and the geodesy in :mod:`core.geodesy`.
"""

from __future__ import annotations

import math

from core.camera.models import CameraOffset, CameraPose
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.models import AircraftState, GeoPosition

__all__ = ["derive_camera_offset", "resolve_camera_pose"]

#: Exact by definition. Module-private, the convention ``core.atmosphere`` and
#: ``core.local_frame`` already use for the same constant.
_METRES_PER_FOOT = 0.3048

#: How many times :func:`derive_camera_offset` re-projects its estimate and
#: adds the leftover. One pass already takes the residual from centimetres to
#: well under a micrometre (the correction is a smooth second-order term, so
#: each pass roughly squares the relative error); the second is free insurance
#: at two geodesic solutions, and the whole loop runs once per saved-position
#: read.
_INVERSE_REFINEMENTS = 2


def _normalise_heading(heading_deg: float) -> float:
    """Fold an angle into ``[0, 360)``.

    The explicit 360.0 guard is not decoration: ``-1e-15 % 360.0`` is exactly
    ``360.0``, which is outside the interval this promises — the same trap
    ``core.geodesy._normalise_bearing`` documents.
    """
    folded = heading_deg % 360.0
    return 0.0 if folded == 360.0 else folded


def _signed_relative_deg(angle_deg: float) -> float:
    """Fold a bearing *difference* into ``[-180, 180]`` — ``CameraOffset``'s own bounds."""
    return (angle_deg + 180.0) % 360.0 - 180.0


def _aircraft_position(state: AircraftState) -> GeoPosition:
    """The aircraft's reference point, as the geodesy functions want it."""
    return GeoPosition(
        latitude=state.latitude,
        longitude=state.longitude,
        altitude_ft=state.altitude_ft,
    )


def _offset_point(state: AircraftState, forward_m: float, right_m: float) -> GeoPosition:
    """Where ``forward_m``/``right_m`` from the aircraft lands, horizontally.

    Two sequential geodesic hops. Altitude is untouched — the vertical axis is
    a plain feet/metres conversion and never involves the ellipsoid.
    """
    ahead = point_at_distance_and_bearing(
        _aircraft_position(state), forward_m / METRES_PER_NAUTICAL_MILE, state.heading_deg
    )
    return point_at_distance_and_bearing(
        ahead, right_m / METRES_PER_NAUTICAL_MILE, state.heading_deg + 90.0
    )


def _decompose(
    state: AircraftState, origin: GeoPosition, target: GeoPosition
) -> tuple[float, float]:
    """``origin`` -> ``target`` as (forward, right) metres on the aircraft's axes.

    Plane trigonometry on one inverse geodesic solution. Exact only for a
    single hop; :func:`derive_camera_offset` corrects the rest.
    """
    distance_nm, bearing_deg = distance_and_bearing(origin, target)
    distance_m = distance_nm * METRES_PER_NAUTICAL_MILE
    relative_rad = math.radians(_signed_relative_deg(bearing_deg - state.heading_deg))
    return distance_m * math.cos(relative_rad), distance_m * math.sin(relative_rad)


def resolve_camera_pose(state: AircraftState, offset: CameraOffset) -> CameraPose:
    """``offset`` -> an absolute :class:`~core.camera.models.CameraPose`, against ``state``.

    Two sequential geodesic hops: ``forward_m`` along the aircraft's current
    heading, then ``right_m`` along that heading + 90°. ``up_m`` is added to
    the aircraft's altitude, converted from metres. The camera's own heading is
    ``state.heading_deg + offset.look_offset_deg`` folded into ``[0, 360)``;
    ``pitch_deg`` and ``zoom_ratio`` pass through unchanged (D5).

    Worked example from the design (§3), hand-checkable: an aircraft on heading
    090° with ``forward_m=50, right_m=0, up_m=20, look_offset_deg=0`` puts the
    camera 50 m away on a true bearing of 090°, ``20 / 0.3048 ≈ 65.6`` ft
    higher, looking on heading exactly 90.0°.
    """
    camera = _offset_point(state, offset.forward_m, offset.right_m)
    return CameraPose(
        position=GeoPosition(
            latitude=camera.latitude,
            longitude=camera.longitude,
            altitude_ft=state.altitude_ft + offset.up_m / _METRES_PER_FOOT,
        ),
        heading_deg=_normalise_heading(state.heading_deg + offset.look_offset_deg),
        pitch_deg=offset.pitch_deg,
        zoom_ratio=offset.zoom_ratio,
    )


def derive_camera_offset(state: AircraftState, pose: CameraPose) -> CameraOffset:
    """The inverse of :func:`resolve_camera_pose`.

    For whichever adapter can read back an absolute camera pose: decomposes the
    vector from the aircraft to ``pose`` onto the aircraft's forward/right
    axes — one inverse geodesic solution and plane trigonometry for a first
    estimate, then :data:`_INVERSE_REFINEMENTS` passes that re-resolve that
    estimate and add whatever is left over.

    **The refinement is load-bearing, and the design's own §6 estimate of the
    error without it was optimistic.** Plane trigonometry over a two-hop
    geodesic composition is not off by the triangle's spherical excess (which
    would indeed be micrometres here) but by the *curvature of the hops
    themselves*: a geodesic launched due east does not hold its latitude, and
    that deviation goes as ``distance^2 / earth radius * tan(latitude)``. At the
    model's ±500 m bound it measures **33 mm at 40° north and 145 mm at 75°** —
    small in absolute terms, but two orders of magnitude past the millimetre
    §8.1 asks the round trip to hold, and it grows with latitude exactly where
    a "look at the aircraft from the left" framing would quietly drift.

    Re-projecting the estimate and adding the residual removes it: the same
    grid measures **12 nanometres** after two passes, i.e. float noise.
    ``tests/core/test_camera_geometry.py`` pins the millimetre round trip so
    the claim cannot rot. This is a different problem from the 40 km-scale
    tangent-plane error ``docs/architecture.md`` flags for long teleports —
    same family, four orders of magnitude apart.

    Raises:
        pydantic.ValidationError: when ``pose`` sits outside the envelope
            :class:`~core.camera.models.CameraOffset` allows (further than
            500 m from the aircraft on any axis). A pose that far out is not a
            camera offset this manager can express, and saying so beats
            silently clamping it to something the instructor never framed.
    """
    forward_m, right_m = _decompose(state, _aircraft_position(state), pose.position)
    for _ in range(_INVERSE_REFINEMENTS):
        residual_forward_m, residual_right_m = _decompose(
            state, _offset_point(state, forward_m, right_m), pose.position
        )
        forward_m += residual_forward_m
        right_m += residual_right_m
    return CameraOffset(
        forward_m=forward_m,
        right_m=right_m,
        up_m=(pose.position.altitude_ft - state.altitude_ft) * _METRES_PER_FOOT,
        look_offset_deg=_signed_relative_deg(pose.heading_deg - state.heading_deg),
        pitch_deg=pose.pitch_deg,
        zoom_ratio=pose.zoom_ratio,
    )
