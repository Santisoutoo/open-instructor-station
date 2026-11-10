"""``/api/weather/presets/user/*`` — save, list, and delete user-authored weather presets.

Pure app data (WS-4): these presets live in a small JSON directory
(:class:`~core.weather.user_presets.WeatherPresetStore`), the same posture
``server.camera_routes``' saved-position endpoints take — listing, saving and
deleting never reach a simulator, so none of this is capability-gated. An
adapter that cannot set weather at all still lets an instructor save, browse
and delete presets; only *applying* one needs the capability, and that happens
through the existing ``/api/weather/apply`` endpoint, not here.

**No ``PUT``, by design.** The UI consumer is save/list/reapply/delete only —
reapplying a saved preset means staging its stored ``setup`` client-side and
sending it through ``POST /api/weather/apply`` (weather-manager.md D7: the
server always re-resolves a request, so an already-resolved setup is applied
exactly like any other setup-only request). A route that can never be reached
from the UI is a maintenance burden with no payoff, so it does not exist.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response

from core.weather.user_presets import (
    SavedWeatherPreset,
    SavedWeatherPresetCreate,
    WeatherPresetStoreError,
)
from server._shared import _not_found_or_404
from server.deps import get_weather_preset_store

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/weather/presets/user", tags=["weather"])

_NOT_FOUND = "No saved weather preset {id!r}."
_MAY_BE_DELETED = "No saved weather preset {id!r} — it may already be deleted."


def _store_failed(exc: WeatherPresetStoreError) -> HTTPException:
    """A store *failure* — disk full, permission denied, corrupt content — is a 500.

    Never "not found": :meth:`~core.weather.user_presets.WeatherPresetStore.get`
    and ``delete`` answer ``None``/``False`` for that, and this module turns
    those into 404s of its own.
    """
    logger.warning("Saved weather preset store failed: %s", exc)
    return HTTPException(status_code=500, detail=str(exc))


@router.get("", response_model=list[SavedWeatherPreset])
def list_presets() -> list[SavedWeatherPreset]:
    """Every saved preset, newest ``created_at`` first. Local storage — never a simulator read."""
    try:
        return get_weather_preset_store().list()
    except WeatherPresetStoreError as exc:
        raise _store_failed(exc) from exc


@router.post("", response_model=SavedWeatherPreset, status_code=201)
def create_preset(draft: SavedWeatherPresetCreate) -> SavedWeatherPreset:
    """Save a new preset. The server assigns ``preset_id`` and timestamps."""
    try:
        return get_weather_preset_store().create(draft)
    except WeatherPresetStoreError as exc:
        raise _store_failed(exc) from exc


@router.get("/{preset_id}", response_model=SavedWeatherPreset)
def get_preset(preset_id: str) -> SavedWeatherPreset:
    """One saved preset, in full."""
    try:
        preset = get_weather_preset_store().get(preset_id)
    except WeatherPresetStoreError as exc:
        raise _store_failed(exc) from exc
    return _not_found_or_404(preset, _NOT_FOUND.format(id=preset_id))


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: str) -> Response:
    """Remove a saved preset. 404 with 'may already be deleted' when it is already gone."""
    try:
        deleted = get_weather_preset_store().delete(preset_id)
    except WeatherPresetStoreError as exc:
        raise _store_failed(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=_MAY_BE_DELETED.format(id=preset_id))
    return Response(status_code=204)
