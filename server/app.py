"""The FastAPI application.

Phase 0 surface: health, capabilities, a one-shot state read and a live state
WebSocket. The UI (built separately into ``ui/dist``) is served from ``/`` when
it exists; the server starts perfectly well without it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.models import AircraftState
from core.sim_adapter import Capabilities, SimAdapter
from server.deps import get_adapter

__all__ = ["STATE_STREAM_INTERVAL_S", "UI_DIST", "create_app"]

logger = logging.getLogger(__name__)

#: Live state push rate: 4 Hz is smooth on a map without flooding a tablet.
STATE_STREAM_INTERVAL_S = 0.25

#: Where the separately-built frontend lands. Optional.
UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"

#: The Vite dev server. CORS is permissive because the station is a LAN tool,
#: not a public site.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Connect the adapter on startup, disconnect on shutdown.

    A simulator that is not running must not stop the server from starting:
    the UI needs to come up and show "disconnected" rather than fail to load.
    """
    adapter: SimAdapter = get_adapter()
    try:
        await adapter.connect()
    except Exception:
        logger.exception("Adapter %r failed to connect at startup", adapter.name)
    try:
        yield
    finally:
        with suppress(Exception):
            await adapter.disconnect()


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="Open Instructor Station",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, Any]:
        """Liveness plus which simulator we are talking to."""
        adapter = get_adapter()
        return {
            "status": "ok",
            "adapter": adapter.name,
            "connected": adapter.is_connected,
        }

    @app.get("/api/capabilities", tags=["system"], response_model=Capabilities)
    async def capabilities() -> Capabilities:
        """What the active adapter supports. The UI disables the rest."""
        return get_adapter().capabilities

    @app.get("/api/state", tags=["aircraft"], response_model=AircraftState)
    async def state() -> AircraftState:
        """One snapshot of the user aircraft."""
        return await get_adapter().get_aircraft_state()

    @app.websocket("/ws/state")
    async def state_socket(websocket: WebSocket) -> None:
        """Push the aircraft state at ~4 Hz until the client goes away."""
        await websocket.accept()
        adapter = get_adapter()
        try:
            async for aircraft_state in adapter.stream_state(STATE_STREAM_INTERVAL_S):
                await websocket.send_text(aircraft_state.model_dump_json())
        except WebSocketDisconnect:
            logger.debug("State WebSocket client disconnected")
        except Exception:
            logger.exception("State stream failed; closing the WebSocket")
            with suppress(Exception):
                await websocket.close(code=1011)

    _mount_ui(app)
    return app


def _mount_ui(app: FastAPI) -> None:
    """Serve ``ui/dist`` at ``/`` if it has been built, otherwise do nothing."""
    if not UI_DIST.is_dir():
        logger.info("No built UI at %s; serving the API only", UI_DIST)
        return
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
