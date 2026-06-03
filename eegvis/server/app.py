"""FastAPI application factory.

Endpoints:
    GET  /             browser app (built Vite app, or a placeholder page)
    GET  /api/status   current connection/stream status (JSON)
    GET  /api/config   effective runtime config (JSON)
    GET  /api/electrodes  electrode metadata for the frontend
    WS   /ws/eeg       realtime processed frames

The :class:`Engine` (source -> pipeline -> broadcast) is started on app
startup and stopped on shutdown. A lightweight status broadcaster keeps clients
informed of connection changes a few times a second.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import AppConfig
from .engine import Engine
from .static import WEB_DIST, frontend_built, placeholder_html
from .websocket import ConnectionManager


def create_app(config: AppConfig, synthetic: bool = False) -> FastAPI:
    manager = ConnectionManager()
    engine = Engine(config, manager, synthetic=synthetic)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engine.start()
        status_task = asyncio.create_task(_status_broadcaster(engine))
        try:
            yield
        finally:
            status_task.cancel()
            with suppress(asyncio.CancelledError):
                await status_task
            await engine.stop()

    app = FastAPI(title="eegvis", lifespan=lifespan)
    app.state.engine = engine
    app.state.config = config

    @app.get("/api/status")
    async def api_status() -> JSONResponse:
        return JSONResponse(engine.status.model_dump())

    @app.get("/api/config")
    async def api_config() -> JSONResponse:
        return JSONResponse(config.model_dump())

    @app.get("/api/electrodes")
    async def api_electrodes() -> JSONResponse:
        from ..assets.electrodes_cgx import ELECTRODES

        return JSONResponse(
            {
                "scale": 1.0,
                "electrodes": [
                    {"name": e.name, "position": e.as_list()} for e in ELECTRODES
                ],
            }
        )

    @app.websocket("/ws/eeg")
    async def ws_eeg(ws: WebSocket) -> None:
        await manager.connect(ws)
        # Send current status immediately on connect.
        await manager.send_json(ws, engine.status.model_dump())
        if engine.latest_frame is not None:
            await manager.send_json(ws, engine.latest_frame.model_dump())
        try:
            while True:
                # We don't expect client messages, but keep the socket alive and
                # detect disconnects.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(ws)

    # Serve frontend last so /api and /ws take precedence.
    if frontend_built():
        app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="static")
    else:
        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            return HTMLResponse(
                placeholder_html(config.server.host, config.server.port)
            )

    return app


async def _status_broadcaster(engine: Engine, interval: float = 2.0) -> None:
    """Periodically re-broadcast status so clients see connection changes."""
    last = None
    while True:
        current = json.dumps(engine.status.model_dump(), sort_keys=True)
        if current != last and engine.manager.client_count:
            await engine.broadcast_status()
            last = current
        await asyncio.sleep(interval)
