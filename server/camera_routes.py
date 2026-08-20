"""``/api/camera/*`` — switch the simulator's view, save and recall camera positions.

Per ``docs/designs/camera-manager.md`` §2.

**Command-shaped, and deliberately without a read-back.** ``/view`` and
``/positions/{id}/apply`` answer with an *echo* of what was commanded, never
with the camera's current state: ``SimAdapter`` exposes no read of the current
named view (D6), because X-Plane's own view-type dataref does not map cleanly
onto this catalogue — a user-orbited camera has no honest id. The panel
highlights the last view it asked for, as client state, and nothing here
pretends to reconcile that against the simulator.

**Two independent gates, and a third that is not a gate at all.** The group
capability ``can_control_camera`` refuses with 501; the manifest's per-view
``supported`` and its ``custom_positions_supported`` sibling (D3) refuse with
501 and the manifest's own sentence — free positioning may need the optional
in-sim bridge on an install where the named views work perfectly (D7, §5.2).
"There is no free-camera pose to save right now" is neither: it is a **state
precondition**, so it is a 409 (D9), the same posture the Pushback Manager's
D8 takes for "not on the ground".

The saved positions themselves never reach a simulator — they live in a small
JSON directory (:class:`~core.camera.store.CameraPositionStore`, D8), so
listing and deleting are capability-free.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool

from core.camera.models import (
    CameraCommandResult,
    CameraManifest,
    CameraViewId,
    CameraViewRequest,
    SaveCameraPositionRequest,
    SavedCameraPosition,
)
from core.camera.store import CameraPositionStore, CameraPositionStoreError
from core.sim_adapter import CapabilityNotSupported
from server.deps import get_adapter, get_camera_position_store

if TYPE_CHECKING:
    from core.sim_adapter import SimAdapter

__all__ = ["CAPABILITY_UNAVAILABLE_STATUS", "NO_LIVE_OFFSET_DETAIL", "router"]

logger = logging.getLogger(__name__)

#: Mirrors ``server.app.CAPABILITY_UNAVAILABLE_STATUS``. Duplicated rather than
#: imported to keep the import edge one-way: ``app`` includes these routers.
CAPABILITY_UNAVAILABLE_STATUS = 501

#: The 409 body (D9, §2.1). A state precondition, not a capability failure:
#: the adapter *can* position the free camera, there is simply no pose to
#: capture until the instructor is in it.
NO_LIVE_OFFSET_DETAIL = (
    "Cannot save a camera position right now — switch to the drone/free camera first."
)

_NOT_FOUND = "No saved camera position {id!r}."
_MAY_BE_DELETED = "No saved camera position {id!r} — it may already be deleted."

router = APIRouter(prefix="/api/camera", tags=["camera"])


# ---------------------------------------------------------------------------
# Gating (§2.1)
# ---------------------------------------------------------------------------


def _require_capability(adapter: SimAdapter) -> None:
    """Refuse up front when the adapter has not declared ``can_control_camera``."""
    if not adapter.capabilities.can_control_camera:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare can_control_camera, so it cannot control the camera.",
        )


async def _require_view(adapter: SimAdapter, view_id: CameraViewId) -> None:
    """Refuse when either the group capability or this one view is unsupported.

    Nobody should reach this: the panel disables the button from
    ``/manifest`` before a request is sent (§7.3). Reaching it means a caller
    ignored the manifest, and the same 501 applies either way — a well-formed
    request the active simulator has no implementation behind.
    """
    _require_capability(adapter)
    manifest = await adapter.get_camera_support()
    support = next((entry for entry in manifest.views if entry.view_id == view_id), None)
    if support is None:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"The {adapter.name!r} adapter's camera manifest carries no entry "
            f"for {view_id!r}.",
        )
    if not support.supported:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=support.reason or f"{view_id!r} is not supported on this adapter.",
        )


async def _require_custom_positions(adapter: SimAdapter, what: str) -> None:
    """Refuse when the adapter cannot reach the free camera at all (D3/D7).

    Separate from :func:`_require_capability` on purpose: named-view switching
    and free positioning are plausibly different reliability tiers on the same
    adapter, and an install where only the first works must still get its view
    grid.
    """
    _require_capability(adapter)
    manifest = await adapter.get_camera_support()
    if not manifest.custom_positions_supported:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=manifest.custom_positions_reason
            or f"The {adapter.name!r} adapter cannot {what}: free-camera positioning "
            f"is unavailable on this install.",
        )


def _store_failed(exc: CameraPositionStoreError) -> HTTPException:
    """A store *failure* — disk full, permission denied, corrupt file — is a 500.

    Never "not found": :meth:`~core.camera.store.CameraPositionStore.get` and
    ``delete`` answer ``None``/``False`` for that, and this module turns those
    into 404s of its own.
    """
    logger.warning("Saved camera position store failed: %s", exc)
    return HTTPException(status_code=500, detail=str(exc))


def _require_saved(store: CameraPositionStore, position_id: str) -> SavedCameraPosition:
    """One saved position, or 404. Blocking: called through ``run_in_threadpool``."""
    try:
        saved = store.get(position_id)
    except CameraPositionStoreError as exc:
        raise _store_failed(exc) from exc
    if saved is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND.format(id=position_id))
    return saved


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/manifest", response_model=CameraManifest)
async def get_manifest() -> CameraManifest:
    """Per-view support plus ``custom_positions_supported``, resolved against the adapter.

    Capability-free (§2.1, the ``get_failure_support`` posture): it answers
    "what could I do here?" even when the answer is "nothing, and here is why"
    for every entry.
    """
    adapter = get_adapter()
    support = await adapter.get_camera_support()
    return CameraManifest(
        adapter=adapter.name,
        caveat=support.caveat,
        views=support.views,
        custom_positions_supported=support.custom_positions_supported,
        custom_positions_reason=support.custom_positions_reason,
    )


@router.post("/view", response_model=CameraCommandResult)
async def set_view(request: CameraViewRequest) -> CameraCommandResult:
    """Switch to a named view now. Idempotent — asking for the current view is a no-op."""
    adapter = get_adapter()
    await _require_view(adapter, request.view_id)
    try:
        await adapter.set_camera_view(request.view_id)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return CameraCommandResult(view_id=request.view_id)


@router.get("/positions", response_model=list[SavedCameraPosition])
def list_positions() -> list[SavedCameraPosition]:
    """Every saved position, in creation order. Local storage — never a simulator read."""
    try:
        return list(get_camera_position_store().list())
    except CameraPositionStoreError as exc:
        raise _store_failed(exc) from exc


@router.post("/positions", response_model=SavedCameraPosition)
async def save_position(request: SaveCameraPositionRequest) -> SavedCameraPosition:
    """Read the camera's current free pose and save it under a name.

    409 when there is no such pose (D9) — the instructor is in a named view,
    or the adapter cannot read one. That is a state the panel can fix by
    switching to the drone camera, which is why it is not the 501 an
    unsupported *capability* gets.
    """
    adapter = get_adapter()
    await _require_custom_positions(adapter, "save a camera position")
    offset = await adapter.get_camera_offset()
    if offset is None:
        raise HTTPException(status_code=409, detail=NO_LIVE_OFFSET_DETAIL)
    store = get_camera_position_store()
    try:
        return await run_in_threadpool(store.save, request.name, offset)
    except CameraPositionStoreError as exc:
        raise _store_failed(exc) from exc


@router.post("/positions/{position_id}/apply", response_model=CameraCommandResult)
async def apply_position(position_id: str) -> CameraCommandResult:
    """Recall a saved position, resolved fresh against live aircraft state (D4).

    The stored offset is aircraft-relative, so what the instructor gets back is
    the same *framing* rather than the same patch of sky — the adapter resolves
    it against wherever the aircraft is at write time.
    """
    adapter = get_adapter()
    await _require_custom_positions(adapter, "recall a saved camera position")
    store = get_camera_position_store()
    saved = await run_in_threadpool(_require_saved, store, position_id)
    try:
        await adapter.set_camera_offset(saved.offset)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return CameraCommandResult(offset=saved.offset)


@router.delete("/positions/{position_id}", status_code=204)
def delete_position(position_id: str) -> Response:
    """Remove a saved position. Never capability-gated — this is local storage.

    404 with "may already be deleted" when it is already gone, the profile
    store's own wording for the same race.
    """
    try:
        deleted = get_camera_position_store().delete(position_id)
    except CameraPositionStoreError as exc:
        raise _store_failed(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=_MAY_BE_DELETED.format(id=position_id))
    return Response(status_code=204)
