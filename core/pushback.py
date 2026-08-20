"""Pushback geometry and models — sim-agnostic, no adapter, no clock.

The instructor pushes the aircraft back from the gate: straight, or through a
circular arc that ends with the nose rotated by a chosen angle. This module
owns the whole vocabulary of that manoeuvre (``docs/designs/pushback-manager.md``):

* the request/result models — here, not in the router (D9, the Position
  Manager's recorded regret);
* :func:`pushback_target`, the one pure function both ``POST
  /api/pushback/preview`` and every adapter's ``pushback()`` call (D7), so the
  two can only disagree if the aircraft moved between the calls;
* :func:`require_on_ground` / :class:`PushbackNotOnGround` — a *precondition*,
  not a capability (D8): an adapter that declares ``can_pushback`` still
  refuses to push an airborne aircraft, and every caller enforces it with the
  same exception.

Geometry (D3/D4): the manoeuvre is described by ``distance_m`` (arc length)
and ``angle_deg`` (total heading change) — a radius is *derived*, never an
input. The arc is resolved in closed form via the chord identity, with
:func:`core.geodesy.point_at_distance_and_bearing` as the only geodesy
primitive — no numeric integration, no ellipsoid maths of its own.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.geodesy import METRES_PER_NAUTICAL_MILE, point_at_distance_and_bearing
from core.models import AircraftState, GeoPosition

__all__ = [
    "PUSHBACK_MAX_ANGLE_DEG",
    "PUSHBACK_MAX_DISTANCE_M",
    "PUSHBACK_PATH_PREVIEW_POINTS",
    "PushbackDirection",
    "PushbackManifest",
    "PushbackNotOnGround",
    "PushbackPreview",
    "PushbackRequest",
    "PushbackResult",
    "PushbackTarget",
    "pushback_target",
    "require_on_ground",
]

#: Where the NOSE ends up (D5): "right" rotates the final heading clockwise
#: from the current one, "left" counter-clockwise.
PushbackDirection = Literal["straight", "left", "right"]

#: Generous, round sanity limits — not a tug's real operating envelope (§10.4).
#: Echoed by ``GET /api/pushback/manifest`` so the UI's sliders never hardcode
#: a second copy of the request's field constraints.
PUSHBACK_MAX_DISTANCE_M: float = 200.0
PUSHBACK_MAX_ANGLE_DEG: float = 180.0

#: Intermediate points along the manoeuvre; + the origin = 9 points total.
PUSHBACK_PATH_PREVIEW_POINTS: int = 8


class PushbackRequest(BaseModel):
    """One pushback instruction.

    ``direction`` describes where the NOSE ends up (D5): ``"right"`` rotates
    the final heading clockwise from the current one, ``"left"``
    counter-clockwise. ``angle_deg`` is the TOTAL heading change over the
    manoeuvre, not a rate — 0 for ``"straight"``, required (> 0) otherwise,
    because an angle of 0 on ``"left"``/``"right"`` would be indistinguishable
    from ``"straight"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: PushbackDirection
    distance_m: float = Field(
        gt=0.0,
        le=PUSHBACK_MAX_DISTANCE_M,
        description=(
            "Arc length (or straight length) the aircraft's reference point travels, metres."
        ),
    )
    angle_deg: float = Field(
        default=0.0,
        ge=0.0,
        le=PUSHBACK_MAX_ANGLE_DEG,
        description="Total heading change through the manoeuvre, degrees. Must be 0 for "
        "'straight', and > 0 for 'left'/'right'.",
    )

    @model_validator(mode="after")
    def _angle_matches_direction(self) -> PushbackRequest:
        if self.direction == "straight" and self.angle_deg != 0.0:
            raise ValueError("angle_deg must be 0 when direction is 'straight'.")
        if self.direction != "straight" and self.angle_deg <= 0.0:
            raise ValueError(
                f"direction={self.direction!r} needs angle_deg > 0; 0 is indistinguishable "
                "from 'straight'."
            )
        return self


class PushbackTarget(BaseModel):
    """The resolved outcome of one :class:`PushbackRequest`, from a given starting state."""

    model_config = ConfigDict(frozen=True)

    position: GeoPosition
    heading_deg: float = Field(ge=0.0, le=360.0)
    path_preview: tuple[GeoPosition, ...] = Field(
        description="PUSHBACK_PATH_PREVIEW_POINTS + 1 points along the manoeuvre, current "
        "position first and target last, for drawing the path. Collinear (2 distinct "
        "endpoints suffice) when direction is 'straight'."
    )


class PushbackPreview(BaseModel):
    """What ``POST /api/pushback/preview`` answers: the geometry, writing nothing."""

    model_config = ConfigDict(frozen=True)

    request: PushbackRequest
    current_position: GeoPosition
    current_heading_deg: float = Field(ge=0.0, le=360.0)
    target: PushbackTarget


class PushbackResult(BaseModel):
    """What ``POST /api/pushback/execute`` answers after the write."""

    model_config = ConfigDict(frozen=True)

    request: PushbackRequest
    #: What was asked for, computed fresh at write time (D7).
    target: PushbackTarget
    #: Read back after the write — the honest verdict, PlacementResult's posture.
    state: AircraftState


class PushbackManifest(BaseModel):
    """Capability + reason, and the exact slider bounds, for ``GET /api/pushback/manifest``."""

    model_config = ConfigDict(frozen=True)

    adapter: str
    supported: bool
    reason: str | None
    max_distance_m: float = PUSHBACK_MAX_DISTANCE_M
    max_angle_deg: float = PUSHBACK_MAX_ANGLE_DEG


class PushbackNotOnGround(ValueError):
    """Raised by :func:`require_on_ground` when the aircraft is airborne.

    A precondition, not a capability (D8): the adapter *can* push back; this
    aircraft, right now, cannot be pushed. The route maps it to 409, never 501.
    """


def require_on_ground(state: AircraftState) -> None:
    """Raise :class:`PushbackNotOnGround` if ``state.on_ground`` is ``False``."""
    if not state.on_ground:
        raise PushbackNotOnGround("Cannot push back — the aircraft is airborne.")


def pushback_target(
    state: AircraftState,
    request: PushbackRequest,
    *,
    preview_points: int = PUSHBACK_PATH_PREVIEW_POINTS,
) -> PushbackTarget:
    """Resolve ``request`` into a :class:`PushbackTarget` from ``state``'s position/heading.

    Geometry (D3/D4): the aircraft's reference point follows a circular arc (or
    a straight line when ``angle_deg == 0``) of radius
    ``distance_m / radians(angle_deg)``, swept through ``angle_deg`` in the
    requested direction, starting tangent to the reciprocal of the current
    heading (``state.heading_deg + 180``).

    A circular arc's chord bisects the angle between its start and end
    tangents — the standard identity this function uses instead of numeric
    integration: ``chord_m = 2 * radius_m * sin(angle_rad / 2)``, at a bearing
    of ``back_bearing_deg + signed_angle_deg / 2`` from the origin. Applying it
    at a fraction of the full angle for ``i`` in ``0..preview_points`` produces
    the path preview on the SAME circle.

    ``direction='straight'`` is ``angle_deg == 0``'s degenerate case:
    chord == ``distance_m``, bearing == ``back_bearing_deg``, heading
    unchanged.
    """
    origin = GeoPosition(
        latitude=state.latitude,
        longitude=state.longitude,
        altitude_ft=state.altitude_ft,
    )
    signed_angle_deg = _signed_angle_deg(request)
    back_bearing_deg = (state.heading_deg + 180.0) % 360.0

    path: list[GeoPosition] = [origin]
    for i in range(1, preview_points + 1):
        fraction = i / preview_points
        chord_m, bearing_deg = _chord_at_fraction(
            request.distance_m, signed_angle_deg, back_bearing_deg, fraction
        )
        path.append(
            point_at_distance_and_bearing(origin, chord_m / METRES_PER_NAUTICAL_MILE, bearing_deg)
        )

    return PushbackTarget(
        position=path[-1],
        heading_deg=(state.heading_deg + signed_angle_deg) % 360.0,
        path_preview=tuple(path),
    )


def _signed_angle_deg(request: PushbackRequest) -> float:
    """D5's sign convention: ``"right"`` is positive (nose clockwise), ``"left"`` negative."""
    if request.direction == "right":
        return request.angle_deg
    if request.direction == "left":
        return -request.angle_deg
    return 0.0


def _chord_at_fraction(
    distance_m: float,
    signed_angle_deg: float,
    back_bearing_deg: float,
    fraction: float,
) -> tuple[float, float]:
    """The chord from the origin to the point ``fraction`` of the way along the manoeuvre.

    Returns ``(chord_m, true_bearing_deg)``. The partial arc up to ``fraction``
    lies on the same circle as the full manoeuvre, so the identity applies with
    the swept angle scaled: its chord is ``2 * radius * sin(swept / 2)`` at
    ``back_bearing + signed_swept_deg / 2``.
    """
    if signed_angle_deg == 0.0:
        return distance_m * fraction, back_bearing_deg
    angle_rad = math.radians(abs(signed_angle_deg))
    radius_m = distance_m / angle_rad
    swept_rad = angle_rad * fraction
    chord_m = 2.0 * radius_m * math.sin(swept_rad / 2.0)
    bearing_deg = (back_bearing_deg + signed_angle_deg * fraction / 2.0) % 360.0
    return chord_m, bearing_deg
