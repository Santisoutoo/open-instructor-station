"""``/api/cockpit/*`` — the per-aircraft cockpit control catalog.

Per ``docs/designs/cockpit-control-catalog.md`` §2.

``GET /catalog`` is capability-free (D1, the ``get_failure_support``/
``get_camera_support`` posture): it answers "what could I actuate here?" even
when the answer is "nothing, and here is why" — no flag, or a flag but no
catalog detected for the loaded aircraft. The other three routes require
``can_control_cockpit`` and refuse with 501 up front.

Everything else is state-precondition (409, D9) or shape-validation (422)
mapped straight from ``core.cockpit.errors`` — never a bespoke adapter
exception reaching this module (the ``WeatherRejected`` precedent).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.cockpit.errors import (
    CockpitCatalogInactive,
    CockpitControlUnknown,
    CockpitPreconditionUnmet,
    CockpitWriteRejected,
)
from core.cockpit.models import (
    CockpitActuation,
    CockpitActuationResult,
    CockpitCatalog,
    CockpitCatalogManifest,
    CockpitStateSnapshot,
)
from core.sim_adapter import CapabilityNotSupported, SimAdapter
from server.constants import CAPABILITY_UNAVAILABLE_STATUS
from server.deps import get_adapter

__all__ = ["CAPABILITY_UNAVAILABLE_STATUS", "router"]

router = APIRouter(prefix="/api/cockpit", tags=["cockpit"])


def _require_capability(adapter: SimAdapter) -> None:
    """Refuse up front when the adapter has not declared ``can_control_cockpit``."""
    if not adapter.capabilities.can_control_cockpit:
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare can_control_cockpit, so it cannot operate cockpit controls.",
        )


def _manifest(adapter: SimAdapter, catalog: CockpitCatalog) -> CockpitCatalogManifest:
    """The REST shape: the catalog plus the adapter's name."""
    return CockpitCatalogManifest(adapter=adapter.name, **catalog.model_dump())


def _panel_control_ids(catalog: CockpitCatalog, panel_id: str) -> list[str]:
    """Every readable control id on ``panel_id``, or a 404 when the panel is unknown."""
    known_panel_ids = {panel.panel_id for panel in catalog.panels}
    if panel_id not in known_panel_ids:
        raise HTTPException(status_code=404, detail=f"No panel {panel_id!r} on this catalog.")
    return [
        control.control_id
        for control in catalog.controls
        if control.panel_id == panel_id and control.readable
    ]


@router.get("/catalog", response_model=CockpitCatalogManifest)
async def get_catalog() -> CockpitCatalogManifest:
    """The active catalog for the loaded aircraft. Always 200 (D1)."""
    adapter = get_adapter()
    catalog = await adapter.get_cockpit_catalog()
    return _manifest(adapter, catalog)


@router.post("/catalog/refresh", response_model=CockpitCatalogManifest)
async def refresh_catalog() -> CockpitCatalogManifest:
    """Force re-detection and drop every cached binding id. Idempotent."""
    adapter = get_adapter()
    _require_capability(adapter)
    try:
        catalog = await adapter.refresh_cockpit_catalog()
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    return _manifest(adapter, catalog)


@router.get("/state", response_model=CockpitStateSnapshot)
async def get_state(panel: str | None = Query(default=None)) -> CockpitStateSnapshot:
    """Confirmed values of the readable controls, optionally scoped to one panel."""
    adapter = get_adapter()
    _require_capability(adapter)
    catalog = await adapter.get_cockpit_catalog()
    control_ids = _panel_control_ids(catalog, panel) if panel is not None else None
    return await adapter.read_cockpit_states(control_ids)


@router.post("/actuate", response_model=CockpitActuationResult)
async def actuate(actuation: CockpitActuation) -> CockpitActuationResult:
    """One actuation, confirmed by read-back."""
    adapter = get_adapter()
    _require_capability(adapter)
    try:
        return await adapter.actuate_cockpit_control(actuation)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc
    except CockpitCatalogInactive as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CockpitControlUnknown as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CockpitPreconditionUnmet as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CockpitWriteRejected as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
