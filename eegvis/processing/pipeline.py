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
    AsymmetryPayload,
    EEGChunk,
    EEGFramePayload,
    FFTPayload,
    ProcessingState,
    QualityPayload,
    StreamMetadata,
)
from .filters import BandpassProcessor, NotchProcessor
from .registry import create_processor

# Output keys that are a per-sample stream rather than a current value: they are
# emitted only on the tick a processor actually runs, never reused between runs.
STREAMING_KEYS: tuple[str, ...] = ()
# Dict-valued outputs that several processors contribute to: merge rather than
# overwrite so each processor adds its own keys (e.g. per-channel features).
MERGE_KEYS = ("features",)


def _merge_outputs(dst: dict, out: dict) -> None:
    """Fold a processor's output into the accumulated frame outputs.

    MERGE_KEYS (e.g. ``features``) are dict-merged so multiple processors can
    each contribute entries; everything else overwrites.
    """
    for key, value in out.items():
        if key in MERGE_KEYS and isinstance(value, dict):
            dst.setdefault(key, {}).update(value)
        else:
            dst[key] = value


class Pipeline:
    def __init__(self, config: ProcessingConfig):
        self.config = config
        # Built-in global filter front-end (always present, runtime-controllable,
        # off by default). notch -> bandpass, then any extra configured filters
        # (e.g. car). The chain runs every tick and produces the filtered window.
        self.notch = NotchProcessor(enabled=False, hz=50.0)
        self.bandpass = BandpassProcessor(enabled=False, low_hz=1.0, high_hz=45.0)
        self.filters = [self.notch, self.bandpass] + [
            create_processor(p.name, p.enabled, p.options()) for p in config.filters
        ]
        # The extractor fan-out (order-independent feature extractors).
        self.processors = [
            create_processor(p.name, p.enabled, p.options())
            for p in config.processors
        ]
        # Global run cadence — applies to ALL processors, not per-processor:
        #   "realtime" / "per-sample" -> run every tick that has new samples
        #   "frequency"               -> run at most run_hz times per second
        # Between runs the last (non-streaming) outputs are reused so frames
        # stay populated at the broadcast rate.
        self.run_mode: str = getattr(config, "run_mode", "realtime")
        self.run_hz: float = float(getattr(config, "run_hz", 30.0))
        self._last_run_t: float = -1e9
        self._persistent: dict = {}
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

    def set_run(self, mode: str | None = None, hz: float | None = None) -> None:
        """Set the global processor run cadence at runtime (all processors)."""
        if mode in ("realtime", "frequency", "per-sample"):
            self.run_mode = mode
        if hz:
            self.run_hz = float(hz)

    def set_bandpass(
        self,
        enabled: bool | None = None,
        low_hz: float | None = None,
        high_hz: float | None = None,
    ) -> None:
        """Enable/retune the global bandpass at runtime (feeds all extractors)."""
        if low_hz is not None and high_hz is not None:
            self.bandpass.set_band(low_hz, high_hz)
        if enabled is not None:
            self.bandpass.enabled = bool(enabled)

    def set_notch(self, enabled: bool | None = None, hz: float | None = None) -> None:
        """Enable/retune the global notch at runtime."""
        if hz is not None:
            self.notch.set_freq(hz)
        if enabled is not None:
            self.notch.enabled = bool(enabled)

    def set_fft_source(self, source: str) -> None:
        """Switch the FFT spectrum between the raw and filtered window."""
        if source in ("raw", "filtered"):
            for proc in self.processors:
                if proc.name == "fft":
                    proc.input = source

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
            filtered_data=np.zeros((self._window_samples, n_ch), dtype=np.float64),
            rolling_timestamps=np.zeros(self._window_samples, dtype=np.float64),
            frame_index=0,
            eeg_channel_indices=metadata.eeg_channel_indices(),
        )
        self._pending_raw = []
        self._persistent = {}
        self._last_run_t = -1e9
        for p in self.filters + self.processors:
            p.configure(metadata)
            p.reset()

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
        fbuf = state.filtered_data  # seeded with raw; the filter chain rewrites it
        ts = state.rolling_timestamps
        w = self._window_samples
        if n >= w:
            new = chunk.data[-w:, : buf.shape[1]]
            buf[:] = new
            if fbuf is not None:
                fbuf[:] = new
            ts[:] = chunk.timestamps[-w:]
        else:
            buf[:-n] = buf[n:]
            buf[-n:] = chunk.data[:, : buf.shape[1]]
            if fbuf is not None:
                fbuf[:-n] = fbuf[n:]
                fbuf[-n:] = chunk.data[:, : fbuf.shape[1]]
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
        """Assemble a frame, running the processors if the global cadence is due.

        Called every engine tick (at output_hz), independent of when chunks
        arrive. The filter chain runs every tick (keeping the filtered window in
        lockstep); the extractor run cadence is global (see :attr:`run_mode`), and
        on ticks where the extractors don't run the last outputs are reused so the
        broadcast stream stays steady.
        """
        state = self._state
        if state is None:
            return None
        state.frame_index += 1
        setattr(state, "_output_hz", self.config.output_hz)

        # Filter chain: run EVERY tick on the new samples so the filtered window
        # stays in lockstep with the raw window (the extractor cadence below only
        # throttles feature recomputation, never the signal front-end).
        for filt in self.filters:
            if filt.enabled:
                filt.process(state)

        state.samples_since_run += state.last_appended
        if self.run_mode == "frequency":
            due = (now - self._last_run_t) >= (1.0 / max(self.run_hz, 0.01))
        else:  # realtime / per-sample -> run whenever new samples arrived
            due = state.last_appended > 0

        outputs = dict(self._persistent)  # reuse last current-values by default
        for k in STREAMING_KEYS:
            outputs.pop(k, None)
        if due:
            self._last_run_t = now
            fresh: dict = {}
            setattr(state, "_frame_outputs", fresh)  # processors see prior outputs
            for proc in self.processors:
                if proc.enabled:
                    _merge_outputs(fresh, proc.process(state))
            state.samples_since_run = 0
            # Persist current-value outputs; stream outputs pass through once.
            for key, value in fresh.items():
                if key not in STREAMING_KEYS:
                    self._persistent[key] = value
            outputs.update(fresh)

        raw_samples = self._pending_raw
        self._pending_raw = []
        # The post-filter version of those same new samples (== raw if no filter).
        filtered_samples: list = []
        n = min(len(raw_samples), state.valid_samples)
        if n and state.filtered_data is not None and state.eeg_channel_indices:
            filtered_samples = (
                state.filtered_data[-n:, state.eeg_channel_indices]
                .astype(float)
                .tolist()
            )
        return self._assemble(state, outputs, raw_samples, filtered_samples)

    def process(self, chunk: EEGChunk) -> EEGFramePayload | None:
        """Convenience for tests: ingest one chunk and emit a frame."""
        import time

        self.ingest(chunk)
        return self.emit(time.monotonic())

    def _assemble(
        self,
        state: ProcessingState,
        outputs: dict,
        raw_samples: list,
        filtered_samples: list,
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
        features = outputs.get("features", {})
        asym = outputs.get("asymmetry")
        asym_payload = AsymmetryPayload(**asym) if asym else None
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
            filtered_samples=filtered_samples,
            latest=latest,
            normalized=normalized,
            bands=bands,
            features=features,
            asymmetry=asym_payload,
            fft=fft_payload,
            short_fourier=short_fourier,
            quality=QualityPayload(
                samples_received=self._samples_received,
                dropped_chunks=self._dropped_chunks,
            ),
        )
