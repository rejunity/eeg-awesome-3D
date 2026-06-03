"""Realtime engine: data source -> pipeline -> broadcast.

Runs as an asyncio task ticking at ``processing.output_hz``. Each tick it
gathers whatever samples have arrived (synthetic generation, or chunks drained
from the LSL receiver thread's queue), runs the processing pipeline, and pushes
the latest frame to all connected WebSocket clients.

LSL sampling lives on its own thread (see :class:`LSLReceiver`); the engine
never blocks on it. Only the most recent frame is broadcast, so a slow browser
or a burst of samples never builds an unbounded backlog.
"""

from __future__ import annotations

import asyncio
import queue
import time

from ..config import AppConfig
from ..lsl.discovery import LSLNotAvailable
from ..lsl.receiver import LSLReceiver
from ..lsl.synthetic import SyntheticStream
from ..models import EEGChunk, EEGFramePayload, StatusPayload, StreamInfoPayload, StreamMetadata
from ..processing.pipeline import Pipeline
from .websocket import ConnectionManager


class Engine:
    def __init__(
        self,
        config: AppConfig,
        manager: ConnectionManager,
        synthetic: bool = False,
    ):
        self.config = config
        self.manager = manager
        self.force_synthetic = synthetic
        self.pipeline = Pipeline(config.processing)

        self.mode = "disconnected"
        self.status = StatusPayload(connected=False, mode="disconnected", message="starting")
        self.latest_frame: EEGFramePayload | None = None

        self._synthetic: SyntheticStream | None = None
        self._receiver: LSLReceiver | None = None
        self._chunk_queue: "queue.Queue[EEGChunk]" = queue.Queue(maxsize=256)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._configured_for: StreamMetadata | None = None

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        self._stop.clear()
        await self._init_source()
        self._task = asyncio.create_task(self._run(), name="eeg-engine")

    async def stop(self) -> None:
        self._stop.set()
        if self._receiver is not None:
            self._receiver.stop()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _init_source(self) -> None:
        if self.force_synthetic:
            self._start_synthetic("synthetic mode requested")
            return
        # Try LSL; fall back to synthetic only if configured.
        try:
            self._receiver = LSLReceiver(
                self.config.stream,
                on_chunk=self._enqueue_chunk,
                on_status=self._on_lsl_status,
            )
            self._receiver.start()
            self.mode = "lsl"
            self._set_status(False, "lsl", "searching for LSL stream")
        except LSLNotAvailable as exc:
            if self.config.stream.synthetic_fallback:
                self._start_synthetic(f"LSL unavailable: {exc}")
            else:
                self._set_status(False, "disconnected", str(exc))

    def _start_synthetic(self, message: str) -> None:
        self._synthetic = SyntheticStream(self.config.synthetic, start_time=time.monotonic())
        self.mode = "synthetic"
        self.pipeline.configure(self._synthetic.metadata)
        self._configured_for = self._synthetic.metadata
        self._set_status(True, "synthetic", message, self._synthetic.metadata)

    # -- LSL callbacks (called from receiver thread) -------------------------

    def _enqueue_chunk(self, chunk: EEGChunk) -> None:
        try:
            self._chunk_queue.put_nowait(chunk)
        except queue.Full:
            # Drop oldest to keep latency bounded.
            try:
                self._chunk_queue.get_nowait()
                self._chunk_queue.put_nowait(chunk)
            except queue.Empty:
                pass

    def _on_lsl_status(self, state: str, connected: bool, metadata: StreamMetadata | None) -> None:
        msg = {
            "searching": "searching for LSL stream",
            "connected": "connected to LSL stream",
            "reconnecting": "stream lost, reconnecting",
        }.get(state, state)
        if metadata is not None:
            self._configured_for = None  # force reconfigure on next chunk
        self._set_status(connected, "lsl", msg, metadata)

    # -- main loop -----------------------------------------------------------

    async def _run(self) -> None:
        period = 1.0 / max(self.config.processing.output_hz, 1.0)
        while not self._stop.is_set():
            tick_start = time.monotonic()
            chunk = self._collect_chunk()
            if chunk is not None and chunk.data.shape[0] > 0:
                self._ensure_configured(chunk.metadata)
                frame = self.pipeline.process(chunk)
                if frame is not None:
                    self.latest_frame = frame
                    await self.manager.broadcast_json(frame.model_dump())
            elapsed = time.monotonic() - tick_start
            await asyncio.sleep(max(0.0, period - elapsed))

    def _collect_chunk(self) -> EEGChunk | None:
        if self.mode == "synthetic" and self._synthetic is not None:
            return self._synthetic.pull_chunk(time.monotonic())
        # LSL: drain everything queued since last tick into one chunk.
        chunks: list[EEGChunk] = []
        while True:
            try:
                chunks.append(self._chunk_queue.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return None
        return self._concat(chunks)

    @staticmethod
    def _concat(chunks: list[EEGChunk]) -> EEGChunk:
        import numpy as np

        data = np.concatenate([c.data for c in chunks], axis=0)
        ts = np.concatenate([c.timestamps for c in chunks], axis=0)
        return EEGChunk(data, ts, chunks[-1].metadata)

    def _ensure_configured(self, metadata: StreamMetadata) -> None:
        if self._configured_for is metadata:
            return
        self.pipeline.configure(metadata)
        self._configured_for = metadata
        self._set_status(True, self.mode, "streaming", metadata)

    # -- status --------------------------------------------------------------

    def _set_status(
        self,
        connected: bool,
        mode: str,
        message: str,
        metadata: StreamMetadata | None = None,
    ) -> None:
        stream = None
        if metadata is not None:
            stream = StreamInfoPayload(
                name=metadata.name,
                type=metadata.type,
                source_id=metadata.source_id,
                channel_count=metadata.channel_count,
                sample_rate=metadata.nominal_srate,
                channel_names=metadata.channel_names,
                channel_types=metadata.channel_types,
            )
        self.status = StatusPayload(
            connected=connected, mode=mode, message=message, stream=stream
        )

    async def broadcast_status(self) -> None:
        await self.manager.broadcast_json(self.status.model_dump())
