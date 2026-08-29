"""The camera catalogue and its vocabulary — sim-agnostic, no dataref name.

Per ``docs/designs/camera-manager.md``:

* :data:`CameraViewId` / :data:`CAMERA_VIEW_CATALOGUE` / :data:`CAMERA_VIEW_IDS`
  — the closed five-view catalogue (D1), mirroring ``FailureId``'s
  ``Literal`` + tuple-catalogue shape: per-view adapter support genuinely
  varies and needs a reason, not just a bool.
* :class:`CameraViewSupport` / :class:`CameraSupportManifest` — what
  ``get_camera_support()`` answers (D2): every view always appears, in
  catalogue order, unsupported ones carry a reason.
  ``custom_positions_supported`` is a sibling field on the same manifest
  (D3), not a second top-level ``Capabilities`` flag — the named views (fired
  by command) and free positioning (written as a pose) are plausibly
  different reliability tiers on the same adapter.
* :class:`CameraOffset` — a saved position is stored as an *aircraft-relative*
  offset (forward/right/up metres plus a look-direction offset), never a
  world-frame coordinate (D4); pitch is world-frame, the look-direction offset
  is aircraft-heading-relative (D5). Model shape only — the geometry that
  resolves one against a live :class:`~core.models.AircraftState`
  (``core/camera/geometry.py``) is a separate, later track.
* :class:`CameraPose` — the absolute, world-frame pose a :class:`CameraOffset`
  resolves to.
* The request/result models (D6/D9): live here, not in a router, so a future
  Scenario Generator or Training Profile hookup validates against the exact
  model a REST call would.

The saved-position store (``core/camera/store.py``) and the resolver
(``core/camera/geometry.py``) are a later, separate track — this module
carries only the vocabulary the ``SimAdapter`` contract needs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from core.models import GeoPosition

__all__ = [
    "CAMERA_VIEW_CATALOGUE",
    "CAMERA_VIEW_IDS",
    "CameraCommandResult",
    "CameraManifest",
    "CameraOffset",
    "CameraPose",
    "CameraSupportManifest",
    "CameraViewId",
    "CameraViewRequest",
    "CameraViewSpec",
    "CameraViewSupport",
    "SaveCameraPositionRequest",
    "SavedCameraPosition",
]

#: The closed five-view catalogue (D1). The wire format, and the format any
#: future scenario/profile hookup would use. Renaming one after release is a
#: breaking change, exactly like ``FailureId``.
CameraViewId = Literal["cockpit", "chase", "tower", "wing", "drone"]


class CameraViewSpec(BaseModel):
    """One catalogue entry. Sim-agnostic; knows no dataref/command name."""

    model_config = ConfigDict(frozen=True)

    view_id: CameraViewId
    label: str
    description: str


CAMERA_VIEW_CATALOGUE: tuple[CameraViewSpec, ...] = (
    CameraViewSpec(
        view_id="cockpit", label="Cockpit", description="The pilot's own forward-facing view."
    ),
    CameraViewSpec(
        view_id="chase", label="Chase", description="Follows the aircraft from behind and above."
    ),
    CameraViewSpec(
        view_id="tower",
        label="Tower",
        description="Fixed view from the nearest airport tower, when the scenery has one.",
    ),
    CameraViewSpec(
        view_id="wing", label="Wing", description="Mounted on the wing, looking along the fuselage."
    ),
    CameraViewSpec(
        view_id="drone",
        label="Drone / free",
        description="Freely positionable external camera — the base for custom saved positions.",
    ),
)

#: The ``FAILURE_IDS`` pattern: the closed ``Literal``'s own members, derived
#: rather than hand-copied, so the two cannot drift.
CAMERA_VIEW_IDS: tuple[CameraViewId, ...] = get_args(CameraViewId)


class CameraViewSupport(BaseModel):
    """One catalogue entry resolved against one adapter."""

    model_config = ConfigDict(frozen=True)

    view_id: CameraViewId
    supported: bool
    reason: str | None = None


class CameraSupportManifest(BaseModel):
    """What ``get_camera_support()`` answers.

    A capability-free read (D2, the ``get_failure_support`` posture): an
    adapter without ``can_control_camera`` still answers — every view
    unsupported and ``custom_positions_supported=False``, each with a stated
    reason. "No" is an answer, never an exception.
    """

    model_config = ConfigDict(frozen=True)

    caveat: str | None = None
    views: tuple[CameraViewSupport, ...] = Field(
        description="Exactly one entry per CAMERA_VIEW_IDS, in catalogue order."
    )
    custom_positions_supported: bool
    custom_positions_reason: str | None = None


class CameraOffset(BaseModel):
    """A free/drone camera pose, expressed relative to the aircraft's own
    reference point and CURRENT heading (D4) — never a world-frame
    coordinate. Recalling a saved offset resolves it fresh every time
    (``core.camera.geometry``, a later track).
    """

    model_config = ConfigDict(frozen=True)

    forward_m: float = Field(
        ge=-500.0,
        le=500.0,
        description="Metres forward of the aircraft's reference point, along its current "
        "heading. Negative is aft.",
    )
    right_m: float = Field(
        ge=-500.0,
        le=500.0,
        description="Metres to the right of the reference point, perpendicular to the "
        "aircraft's current heading. Negative is left.",
    )
    up_m: float = Field(ge=-500.0, le=500.0, description="Metres above the reference point.")
    look_offset_deg: float = Field(
        ge=-180.0,
        le=180.0,
        description="Camera yaw relative to the aircraft's CURRENT heading (D5). 0 = looking "
        "the same way the aircraft points; +90 = looking to the right of the nose.",
    )
    pitch_deg: float = Field(
        ge=-90.0,
        le=90.0,
        description="Camera pitch, WORLD frame (D5), positive looking up toward the sky — "
        "independent of the aircraft's own pitch attitude.",
    )
    zoom_ratio: float = Field(
        default=1.0,
        gt=0.0,
        le=10.0,
        description="Field-of-view zoom multiplier; 1.0 is the adapter's default FOV.",
    )


class CameraPose(BaseModel):
    """An absolute, world-frame camera pose — what a :class:`CameraOffset` resolves to."""

    model_config = ConfigDict(frozen=True)

    position: GeoPosition
    heading_deg: float = Field(ge=0.0, le=360.0)
    pitch_deg: float = Field(ge=-90.0, le=90.0)
    zoom_ratio: float = Field(gt=0.0, le=10.0)


class CameraViewRequest(BaseModel):
    """``POST /api/camera/view``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    view_id: CameraViewId


class SaveCameraPositionRequest(BaseModel):
    """``POST /api/camera/positions``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=60)


class SavedCameraPosition(BaseModel):
    """One saved custom camera position.

    Built by the adapter's in-memory store or ``core.camera.store``, never by
    a request body — the id and creation timestamp are assigned, not
    supplied.
    """

    model_config = ConfigDict(frozen=True)

    position_id: str = Field(description="Server-assigned opaque id (uuid4 hex).")
    name: str
    offset: CameraOffset
    created_at: datetime = Field(description="UTC.")


class CameraCommandResult(BaseModel):
    """What ``/view`` and ``/positions/{id}/apply`` answer — an echo, not a
    read-back (D6: there is nothing honest to read back into).
    """

    model_config = ConfigDict(frozen=True)

    view_id: CameraViewId | None = None
    offset: CameraOffset | None = None


class CameraManifest(BaseModel):
    """``GET /api/camera/manifest`` — the whole per-view picture the panel gates on."""

    model_config = ConfigDict(frozen=True)

    adapter: str
    caveat: str | None
    views: tuple[CameraViewSupport, ...]
    custom_positions_supported: bool
    custom_positions_reason: str | None
