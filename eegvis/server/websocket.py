"""WebSocket connection manager.

Tracks connected browser clients and broadcasts the latest frame. Frames are
sent best-effort; a slow/broken client is dropped rather than allowed to block
the broadcast. The engine only ever pushes the *latest* frame, so there is no
unbounded queue — stale frames are simply never sent.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        if ws.application_state != WebSocketState.DISCONNECTED:
            with suppress(Exception):
                await ws.close()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast_json(self, message: dict) -> None:
        async with self._lock:
            clients = list(self._clients)
        if not clients:
            return
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def send_json(self, ws: WebSocket, message: dict) -> None:
        with suppress(Exception):
            await ws.send_json(message)
