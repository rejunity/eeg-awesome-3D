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
        for p in self.processors:
            p.configure(metadata)
            p.reset()
        self.band_select.configure(metadata)

    def reset(self) -> None:
        if self._metadata is not None:
            self.configure(self._metadata)

    def _append(self, chunk: EEGChunk) -> None:
        """Roll the buffer and append the chunk's samples to the end."""
        assert self._state is not None
        n = chunk.data.shape[0]
        if n == 0:
            return
        self._samples_received += n
        buf = self._state.rolling_data
        ts = self._state.rolling_timestamps
        if n >= self._window_samples:
            buf[:] = chunk.data[-self._window_samples:, : buf.shape[1]]
            ts[:] = chunk.timestamps[-self._window_samples:]
        else:
            buf[:-n] = buf[n:]
            buf[-n:] = chunk.data[:, : buf.shape[1]]
            ts[:-n] = ts[n:]
            ts[-n:] = chunk.timestamps

    def process(self, chunk: EEGChunk) -> EEGFramePayload | None:
        """Run a chunk through the pipeline and assemble a frame payload."""
        if self._state is None or self._metadata is None:
            self.configure(chunk.metadata)
        assert self._state is not None and self._metadata is not None

        self._append(chunk)

        state = self._state
        state.frame_index += 1
        # Expose pipeline-level context to throttled processors.
        setattr(state, "_output_hz", self.config.output_hz)

        outputs: dict = {}
        setattr(state, "_frame_outputs", outputs)
        for proc in self.processors:
            if not proc.enabled:
                continue
            result = proc.process(chunk, state)
            if result:
                outputs.update(result)

        # Band processor runs last so its `latest` reflects the selected band
        # (or raw pass-through) regardless of any configured processors.
        band_out = self.band_select.process(chunk, state)
        if band_out:
            outputs.update(band_out)

        return self._assemble(state, outputs)

    def _assemble(self, state: ProcessingState, outputs: dict) -> EEGFramePayload:
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
