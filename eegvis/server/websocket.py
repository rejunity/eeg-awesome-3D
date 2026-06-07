"""WebSocket connection manager.

Each client has its own buffer and sender task. The engine enqueues messages
*without blocking* (a slow client never stalls the producer), and the per-client
sender flushes everything currently buffered as a single batched message. This
way a render-bound browser that drains slowly still receives all the data (in
larger batches) instead of throttling the server via TCP/WS backpressure.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import WebSocket
from starlette.websockets import WebSocketState

# Per-client cap on buffered messages; oldest are dropped beyond this so a
# stalled client can't grow memory without bound (~10 s at 30 Hz).
MAX_BUFFERED = 300


class _Client:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.buffer: list[dict] = []
        self.event = asyncio.Event()
        self.closed = False
        self.task: asyncio.Task | None = None
        # Rolling counters since the last stats drain (for the broadcast log).
        self.batches = 0
        self.frames = 0

    def enqueue(self, message: dict) -> None:
        self.buffer.append(message)
        overflow = len(self.buffer) - MAX_BUFFERED
        if overflow > 0:
            del self.buffer[:overflow]  # drop oldest
        self.event.set()

    async def run(self) -> None:
        try:
            while not self.closed:
                await self.event.wait()
                self.event.clear()
                if not self.buffer:
                    continue
                batch = self.buffer
                self.buffer = []
                self.batches += 1
                self.frames += len(batch)
                # Send everything accumulated since the last flush as one batch.
                await self.ws.send_json({"type": "batch", "messages": batch})
        except Exception:
            self.closed = True


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, _Client] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        client = _Client(ws)
        client.task = asyncio.create_task(client.run())
        async with self._lock:
            self._clients[ws] = client

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            client = self._clients.pop(ws, None)
        if client is not None:
            client.closed = True
            client.event.set()
            if client.task is not None:
                client.task.cancel()
                with suppress(asyncio.CancelledError):
                    await client.task
        if ws.application_state != WebSocketState.DISCONNECTED:
            with suppress(Exception):
                await ws.close()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def drain_send_stats(self) -> tuple[int, int]:
        """Sum (batches, frames) sent since the last call, then reset counters."""
        batches = frames = 0
        for client in list(self._clients.values()):
            batches += client.batches
            frames += client.frames
            client.batches = 0
            client.frames = 0
        return batches, frames

    async def broadcast_json(self, message: dict) -> None:
        # Non-blocking: enqueue to every client's buffer; sender tasks flush.
        for client in list(self._clients.values()):
            client.enqueue(message)

    async def send_json(self, ws: WebSocket, message: dict) -> None:
        client = self._clients.get(ws)
        if client is not None:
            client.enqueue(message)
