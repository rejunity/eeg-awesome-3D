"""FFT processor.

Computes a Hann-windowed rfft over the most recent ``window_seconds`` of the
rolling buffer for each EEG channel. Emits compact frequency bins (capped at
``max_freq_hz``) and per-channel magnitudes. Throttled to ``update_hz`` so the
payload stays small; between updates the previous result is reused by the
pipeline.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor


class FFTProcessor(EEGProcessor):
    name = "fft"
    output_keys = ("fft",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.window_seconds = float(self.opt("window_seconds", 1.0))
        self.update_hz = float(self.opt("update_hz", 10.0))
        self.max_freq_hz = float(self.opt("max_freq_hz", 45.0))
        self.max_channels = int(self.opt("max_channels", 32))
        self._sample_rate = 0.0
        self._last_emit_frame = -10_000
        self._window: np.ndarray | None = None
        self._window_n = 0

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate

    def _ensure_window(self, n: int) -> np.ndarray:
        if self._window is None or self._window_n != n:
            self._window = np.hanning(n)
            self._window_n = n
        return self._window

    def process(self, state: ProcessingState) -> dict[str, Any]:
        sr = state.sample_rate or self._sample_rate
        if sr <= 0:
            return {}

        # Throttle: only recompute every Nth output frame (output_hz / update_hz).
        # Between emits the pipeline reuses the previous fft block.
        if state.frame_index - self._last_emit_frame < self._emit_interval(state):
            return {}
        self._last_emit_frame = state.frame_index

        segment = self.latest(state, self.window_seconds)  # (win_n, n_eeg)
        win_n = segment.shape[0]
        if win_n < 8 or segment.shape[1] == 0:
            return {}

        window = self._ensure_window(win_n)[:, None]
        windowed = segment * window

        spectrum = np.fft.rfft(windowed, axis=0)
        mags = np.abs(spectrum) / win_n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(win_n, d=1.0 / sr)

        keep = freqs <= self.max_freq_hz
        freqs = freqs[keep]
        mags = mags[keep, :]

        # values[channel][bin]
        n_ch = min(mags.shape[1], self.max_channels)
        values = mags[:, :n_ch].T.astype(float).tolist()

        return {
            "fft": {
                "freqs": freqs.astype(float).tolist(),
                "values": values,
            }
        }

    def _emit_interval(self, state: ProcessingState) -> int:
        """Frames between emits, derived from the pipeline output rate."""
        output_hz = getattr(state, "_output_hz", None) or 30.0
        return max(1, int(round(output_hz / max(self.update_hz, 0.1))))
