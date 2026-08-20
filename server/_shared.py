"""Small pieces of logic reimplemented near-identically across ``server/*_routes.py``.

Leading underscore, matching this codebase's convention for a module that is
not itself a route module (no ``router = APIRouter()``) — it exists to be
imported, never included in ``server.app.create_app()``.
"""

from __future__ import annotations

from fastapi import HTTPException

from core.sim_adapter import SimAdapter
from server.constants import CAPABILITY_UNAVAILABLE_STATUS

__all__ = ["_require_capability"]


def _require_capability(adapter: SimAdapter, flag: str, what: str) -> None:
    """Refuse up front when the adapter has not declared what this needs."""
    if not bool(getattr(adapter.capabilities, flag, False)):
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare {flag}, so it cannot {what}.",
        )
