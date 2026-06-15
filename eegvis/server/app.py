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
    shutdown = IdleShutdown(config, manager)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engine.start()
        status_task = asyncio.create_task(_status_broadcaster(engine))
        # The uvicorn server is attached by the CLI (app.state.uvicorn_server)
        # so idle-shutdown can ask it to exit. Absent in tests -> no-op.
        shutdown.server = getattr(app.state, "uvicorn_server", None)
        try:
            yield
        finally:
            shutdown.cancel()
            status_task.cancel()
            with suppress(asyncio.CancelledError):
                await status_task
            await engine.stop()

    app = FastAPI(title="eegvis", lifespan=lifespan)
    app.state.engine = engine
    app.state.config = config
    app.state.uvicorn_server = None  # set by the CLI before server.run()

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
        _enable_tcp_nodelay(ws)  # avoid Nagle/delayed-ACK stalls on small frames
        shutdown.on_connect()
        # Send current status immediately on connect.
        await manager.send_json(ws, engine.status.model_dump())
        if engine.latest_frame is not None:
            await manager.send_json(ws, engine.latest_frame.model_dump())
        try:
            while True:
                # Client may send small control messages (e.g. band selection).
                text = await ws.receive_text()
                _handle_client_message(engine, text)
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(ws)
            shutdown.on_disconnect()

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


class IdleShutdown:
    """Stop the server shortly after the browser tab closes.

    Arms only once a client has connected (so startup / --no-browser headless
    runs don't exit prematurely). When the last client disconnects, waits
    ``idle_shutdown_grace`` seconds; if no client reconnects in that window
    (a page reload reconnects almost immediately), asks uvicorn to exit.
    """

    def __init__(self, config: AppConfig, manager: ConnectionManager):
        self.config = config
        self.manager = manager
        self.server = None  # uvicorn.Server, attached in lifespan
        self._had_client = False
        self._pending: asyncio.Task | None = None

    def on_connect(self) -> None:
        self._had_client = True
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None

    def on_disconnect(self) -> None:
        if not self.config.server.exit_on_browser_close:
            return
        if not self._had_client or self.manager.client_count > 0:
            return
        if self._pending is None or self._pending.done():
            self._pending = asyncio.create_task(self._wait_then_exit())

    async def _wait_then_exit(self) -> None:
        try:
            await asyncio.sleep(self.config.server.idle_shutdown_grace)
        except asyncio.CancelledError:
            return
        # Still no clients after the grace period -> shut down.
        if self.manager.client_count == 0 and self.server is not None:
            self.server.should_exit = True

    def cancel(self) -> None:
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None


def _enable_tcp_nodelay(ws: WebSocket) -> None:
    """Disable Nagle on the WebSocket's TCP socket (best-effort, uvicorn-specific).

    Without this, the server's small per-frame sends interact with the client's
    TCP delayed-ACK (~200 ms) and stall, capping throughput near 5 Hz.
    """
    import socket as _socket

    try:
        transport = getattr(getattr(ws, "_send", None), "__self__", None)
        transport = getattr(transport, "transport", None)
        sock = transport.get_extra_info("socket") if transport is not None else None
        if sock is not None:
            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
    except Exception:
        pass


def _handle_client_message(engine: Engine, text: str) -> None:
    """Apply a control message from a browser client (best-effort)."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return
    if not isinstance(data, dict):
        return
    if data.get("type") == "set_band_run":
        engine.set_band_run(data.get("mode"), data.get("hz"))
    elif data.get("type") == "set_bandpass":
        engine.set_bandpass(data.get("enabled"), data.get("low_hz"), data.get("high_hz"))
    elif data.get("type") == "set_notch":
        engine.set_notch(data.get("enabled"), data.get("hz"))
    elif data.get("type") == "set_fft_source":
        src = data.get("source")
        if src in ("raw", "filtered"):
            engine.set_fft_source(src)
    elif data.get("type") == "set_mains_hum":
        engine.set_mains_hum(data.get("enabled"), data.get("hz"))


async def _status_broadcaster(engine: Engine, interval: float = 2.0) -> None:
    """Periodically re-broadcast status so clients see connection changes."""
    last = None
    while True:
        current = json.dumps(engine.status.model_dump(), sort_keys=True)
        if current != last and engine.manager.client_count:
            await engine.broadcast_status()
            last = current
        await asyncio.sleep(interval)
