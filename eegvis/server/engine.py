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
import sys
import queue
import time

import numpy as np

from ..config import AppConfig
from ..lsl.discovery import DiscoveredStream, LSLNotAvailable, discover_streams
from ..lsl.receiver import LSLReceiver
from ..lsl.synthetic import SyntheticStream
from ..models import (
    EEGChunk,
    EEGFramePayload,
    StatusPayload,
    StreamDescriptor,
    StreamInfoPayload,
    StreamMetadata,
    StreamsPayload,
)
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
        # Running estimate of the signal RMS, so the debug mains hum is scaled to
        # the stream's own amplitude (works whether it's ~unit synthetic data or
        # microvolt LSL data).
        self._hum_scale: float | None = None
        self._chunk_queue: "queue.Queue[EEGChunk]" = queue.Queue(maxsize=256)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._configured_for: StreamMetadata | None = None
        # Discovered LSL streams (refreshed by the scanner) and the source_id of
        # the currently selected stream ("synthetic" for the generator).
        self.available_streams: list[StreamDescriptor] = []
        self._discovered: list[DiscoveredStream] = []  # raw infos for fast switch
        self._current_source: str | None = None

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
        self._current_source = "synthetic"
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
            self._current_source = metadata.source_id
        self._set_status(connected, "lsl", msg, metadata)

    # -- main loop -----------------------------------------------------------

    async def _run(self) -> None:
        period = 1.0 / max(self.config.processing.output_hz, 1.0)
        sent = 0
        log_t = time.monotonic()
        while not self._stop.is_set():
            tick_start = time.monotonic()
            chunk = self._collect_chunk()
            if chunk is not None and chunk.data.shape[0] > 0:
                self._apply_hum(chunk)
                self._ensure_configured(chunk.metadata)
                self.pipeline.ingest(chunk)
            else:
                self.pipeline.mark_no_data()
            # Emit a frame every tick (at output_hz) once we have a stream, so
            # the broadcast is steady regardless of when chunks arrive. Each
            # processor recomputes per its own cadence.
            if self._configured_for is not None:
                frame = self.pipeline.emit(tick_start)
                if frame is not None:
                    self.latest_frame = frame
                    await self.manager.broadcast_json(frame.model_dump())
                    sent += 1
            # Ground-truth broadcast rate, logged every ~5s while clients listen.
            if tick_start - log_t >= 5.0:
                batches, frames = self.manager.drain_send_stats()
                if self.manager.client_count:
                    dt = tick_start - log_t
                    per_batch = frames / batches if batches else 0.0
                    print(
                        f"[eegvis] broadcasting {sent / dt:.1f} fps; sent "
                        f"{frames} frames in {batches} batches "
                        f"({per_batch:.1f} frames/batch avg) to "
                        f"{self.manager.client_count} client(s)",
                        file=sys.stderr,
                    )
                sent = 0
                log_t = tick_start
            elapsed = time.monotonic() - tick_start
            await asyncio.sleep(max(0.0, period - elapsed))

    def _apply_hum(self, chunk: EEGChunk) -> None:
        """Add a coherent mains-hum line to every EEG channel of a chunk.

        Applied to whatever source is active (synthetic OR real LSL) so the notch
        / CAR are demonstrable on any stream. The amplitude is a *fraction of the
        signal's own RMS* (tracked across chunks), so it's visible whether the
        stream is ~unit synthetic data or microvolt-scale LSL data — a fixed
        absolute amplitude would be invisible against real EEG. The same line is
        added to every channel (common-mode), so CAR removes it too. Uses the
        chunk's absolute timestamps so the sine stays phase-continuous.
        """
        cfg = self.config.synthetic
        if not cfg.mains_hum or cfg.mains_amplitude <= 0 or chunk.data.shape[0] == 0:
            return
        idx = chunk.metadata.eeg_channel_indices() or list(range(chunk.data.shape[1]))
        eeg = chunk.data[:, idx].astype(np.float64)

        # Track the signal std (EMA) BEFORE injecting, so the scale reflects the
        # real signal's AC amplitude (ignoring any DC electrode offset) and the
        # hum amplitude is unit-agnostic.
        mag = float(np.std(eeg))
        if self._hum_scale is None:
            self._hum_scale = mag
        else:
            self._hum_scale = 0.9 * self._hum_scale + 0.1 * mag
        scale = self._hum_scale if self._hum_scale and self._hum_scale > 0 else 1.0

        hum = cfg.mains_amplitude * scale * np.sin(2.0 * np.pi * cfg.mains_hz * chunk.timestamps)
        chunk.data[:, idx] += hum[:, None].astype(chunk.data.dtype)

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

    # -- stream discovery / switching ----------------------------------------

    def _discover(self) -> list[DiscoveredStream]:
        """Blocking: resolve all visible LSL streams."""
        try:
            return discover_streams(timeout=1.0)
        except Exception:
            return []

    async def scan_streams(self) -> None:
        """Refresh the available-stream list (off the event loop)."""
        loop = asyncio.get_event_loop()
        self._discovered = await loop.run_in_executor(None, self._discover)
        self.available_streams = [
            StreamDescriptor(
                name=s.metadata.name,
                source_id=s.metadata.source_id,
                type=s.metadata.type,
                channel_count=s.metadata.channel_count,
                sample_rate=s.metadata.nominal_srate,
            )
            for s in self._discovered
        ]

    def streams_payload(self) -> StreamsPayload:
        synthetic = StreamDescriptor(
            name="Synthetic EEG",
            source_id="synthetic",
            type="EEG",
            channel_count=self.config.synthetic.channel_count,
            sample_rate=self.config.synthetic.sample_rate,
        )
        return StreamsPayload(
            streams=[synthetic, *self.available_streams],
            current=self._current_source,
        )

    async def broadcast_streams(self) -> None:
        await self.manager.broadcast_json(self.streams_payload().model_dump())

    async def select_stream(self, source_id: str | None) -> None:
        """Switch the active source to ``source_id`` ("synthetic" = generator)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._switch_source_blocking, source_id)
        await self.broadcast_status()
        await self.broadcast_streams()

    def _switch_source_blocking(self, source_id: str | None) -> None:
        # Tear down the current source.
        if self._receiver is not None:
            self._receiver.stop()
            self._receiver = None
        self._synthetic = None
        self._configured_for = None
        self._hum_scale = None
        # Drop any chunks still queued from the previous stream.
        try:
            while True:
                self._chunk_queue.get_nowait()
        except queue.Empty:
            pass

        if source_id == "synthetic" or source_id is None:
            self.force_synthetic = True
            self._start_synthetic("synthetic selected")
            return

        # Pin the chosen stream by source_id and (re)start the receiver. Hand it
        # the already-resolved StreamInfo from the last scan so it connects
        # instantly instead of re-resolving (~5 s).
        self.force_synthetic = False
        self.config.stream.source_id = source_id
        self.config.stream.name = None
        preset = next(
            (d for d in self._discovered if d.metadata.source_id == source_id), None
        )
        try:
            self._receiver = LSLReceiver(
                self.config.stream,
                on_chunk=self._enqueue_chunk,
                on_status=self._on_lsl_status,
                preset=preset,
            )
            self._receiver.start()
            self.mode = "lsl"
            self._current_source = source_id
            self._set_status(False, "lsl", "switching to selected stream")
        except LSLNotAvailable as exc:
            self._set_status(False, "disconnected", str(exc))

    def set_band_run(self, mode: str | None, hz: float | None) -> None:
        """Set the global processor run cadence (realtime | frequency | per-sample)."""
        self.pipeline.set_run(mode, hz)

    def set_bandpass(
        self, enabled: bool | None, low_hz: float | None, high_hz: float | None
    ) -> None:
        """Enable/retune the global bandpass that feeds the feature extractors."""
        self.pipeline.set_bandpass(enabled, low_hz, high_hz)

    def set_car(self, enabled: bool) -> None:
        """Enable/disable the global common-average-reference filter."""
        self.pipeline.set_car(enabled)

    def set_physio(self, enabled: bool) -> None:
        """Enable/disable the systemic-physiology (fNIRS) removal filter."""
        self.pipeline.set_physio(enabled)

    def set_notch(self, enabled: bool | None, hz: float | None) -> None:
        """Enable/retune the global notch filter."""
        self.pipeline.set_notch(enabled, hz)

    def set_fft_source(self, source: str) -> None:
        """Switch the FFT spectrum between the raw and filtered window."""
        self.pipeline.set_fft_source(source)

    def set_mains_hum(
        self, enabled: bool | None, hz: float | None, amplitude: float | None = None
    ) -> None:
        """Inject/retune a synthetic mains hum (debug; only affects synthetic mode)."""
        cfg = self.config.synthetic
        if enabled is not None:
            cfg.mains_hum = bool(enabled)
        if hz:
            cfg.mains_hz = float(hz)
        if amplitude is not None:
            cfg.mains_amplitude = float(amplitude)
