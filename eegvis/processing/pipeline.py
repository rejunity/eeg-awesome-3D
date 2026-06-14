"""Processing pipeline.

Owns the rolling buffer and the ordered list of enabled processors. Feeds each
incoming :class:`EEGChunk` through the buffer, runs every processor in order,
accumulates their outputs, and assembles an :class:`EEGFramePayload`.

The pipeline is the only place that knows about processor ordering and the
frame contract; processors stay independent and unaware of each other (they
communicate only through the rolling buffer and the accumulated frame outputs
exposed on the state object).
"""

from __future__ import annotations

import numpy as np

from ..config import ProcessingConfig
from ..models import (
    EEGChunk,
    EEGFramePayload,
    FFTPayload,
    ProcessingState,
    QualityPayload,
    StreamMetadata,
)
from .band_select import BandSelectProcessor
from .registry import create_processor


class Pipeline:
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.processors = [
            create_processor(p.name, p.enabled, p.options())
            for p in config.processors
        ]
        # Always-present, runtime-selectable band processor applied to the raw
        # buffer (before the browser normalises/colours). Defaults to None
        # (raw pass-through).
        self.band_select = BandSelectProcessor()
        self._metadata: StreamMetadata | None = None
        self._state: ProcessingState | None = None
        self._window_samples = 0
        self._samples_received = 0
        self._dropped_chunks = 0
        # Raw EEG samples ingested since the last emit (sent on the next frame).
        self._pending_raw: list = []
        # Last FFT block, reused on frames where the throttled FFT processor
        # produced nothing.
        self._last_fft: dict | None = None

    def set_band(self, band: str | None) -> None:
        """Select the band applied to raw data (None = raw pass-through)."""
        self.band_select.set_band(band)

    @property
    def enabled_processors(self):
        return [p for p in self.processors if p.enabled]

    def configure(self, metadata: StreamMetadata) -> None:
        self._metadata = metadata
        sr = metadata.nominal_srate if metadata.nominal_srate > 0 else 250.0
        self._window_samples = max(int(self.config.rolling_window_seconds * sr), 16)
        n_ch = metadata.channel_count
        self._state = ProcessingState(
            sample_rate=metadata.nominal_srate,
            channel_names=metadata.channel_names,
            rolling_data=np.zeros((self._window_samples, n_ch), dtype=np.float64),
            rolling_timestamps=np.zeros(self._window_samples, dtype=np.float64),
            frame_index=0,
            eeg_channel_indices=metadata.eeg_channel_indices(),
        )
        self._pending_raw = []
        for p in self.processors:
            p.configure(metadata)
            p.reset()
        self.band_select.configure(metadata)

    def reset(self) -> None:
        if self._metadata is not None:
            self.configure(self._metadata)

    def _append(self, chunk: EEGChunk) -> None:
        """Roll the sliding window and append the chunk's samples to the end."""
        assert self._state is not None
        n = chunk.data.shape[0]
        self._state.last_appended = n
        if n == 0:
            return
        self._samples_received += n
        state = self._state
        buf = state.rolling_data
        ts = state.rolling_timestamps
        if n >= self._window_samples:
            buf[:] = chunk.data[-self._window_samples:, : buf.shape[1]]
            ts[:] = chunk.timestamps[-self._window_samples:]
        else:
            buf[:-n] = buf[n:]
            buf[-n:] = chunk.data[:, : buf.shape[1]]
            ts[:-n] = ts[n:]
            ts[-n:] = chunk.timestamps
        state.valid_samples = min(state.valid_samples + n, self._window_samples)

    def ingest(self, chunk: EEGChunk) -> None:
        """Append a chunk's samples to the sliding window (no frame emitted)."""
        if self._state is None or self._metadata is None:
            self.configure(chunk.metadata)
        assert self._state is not None
        self._append(chunk)
        # Stash this chunk's raw EEG samples for the next emit (chunk.data is
        # untouched by processors) so the browser gets full source resolution.
        if chunk.data.shape[0] and self._state.eeg_channel_indices:
            self._pending_raw.extend(
                chunk.data[:, self._state.eeg_channel_indices].astype(float).tolist()
            )

    def mark_no_data(self) -> None:
        """Signal a tick with no new samples (so streaming processors idle)."""
        if self._state is not None:
            self._state.last_appended = 0

    def emit(self, now: float) -> EEGFramePayload | None:
        """Run due processors on the current window and assemble a frame.

        Called every engine tick (at output_hz), independent of when chunks
        arrive — each processor recomputes per its own run cadence, and outputs
        are reused between runs, so the broadcast stream is steady.
        """
        state = self._state
        if state is None:
            return None
        state.frame_index += 1
        setattr(state, "_output_hz", self.config.output_hz)
        has_new = state.last_appended > 0

        outputs: dict = {}
        setattr(state, "_frame_outputs", outputs)
        for proc in self.processors:
            if proc.enabled:
                outputs.update(proc.run(state, now, has_new))
        # Band processor runs last so its `latest` reflects the selected band.
        outputs.update(self.band_select.run(state, now, has_new))

        raw_samples = self._pending_raw
        self._pending_raw = []
        return self._assemble(state, outputs, raw_samples)

    def process(self, chunk: EEGChunk) -> EEGFramePayload | None:
        """Convenience for tests: ingest one chunk and emit a frame."""
        import time

        self.ingest(chunk)
        return self.emit(time.monotonic())

    def _assemble(
        self, state: ProcessingState, outputs: dict, raw_samples: list
    ) -> EEGFramePayload:
        channels = state.eeg_channel_names

        # Always emit the raw last sample per EEG channel (no filtering). A
        # processor may still override `latest`/`normalized` if one is enabled.
        if state.rolling_timestamps.size and state.eeg_channel_indices:
            raw_latest = (
                state.rolling_data[-1, state.eeg_channel_indices].astype(float).tolist()
            )
        else:
            raw_latest = []

        latest = outputs.get("latest", raw_latest)
        normalized = outputs.get("normalized", [])
        bands = outputs.get("bands", {})
        short_fourier = outputs.get("short_fourier")

        fft_block = outputs.get("fft")
        if fft_block is not None:
            self._last_fft = fft_block
        fft_payload = None
        if self._last_fft is not None:
            fft_payload = FFTPayload(**self._last_fft)

        timestamp = (
            float(state.rolling_timestamps[-1])
            if state.rolling_timestamps.size
            else 0.0
        )

        return EEGFramePayload(
            frame_index=state.frame_index,
            timestamp=timestamp,
            sample_rate=state.sample_rate,
            channels=channels,
            raw=raw_latest,
            samples=raw_samples,
            latest=latest,
            normalized=normalized,
            bands=bands,
            fft=fft_payload,
            short_fourier=short_fourier,
            quality=QualityPayload(
                samples_received=self._samples_received,
                dropped_chunks=self._dropped_chunks,
            ),
        )
