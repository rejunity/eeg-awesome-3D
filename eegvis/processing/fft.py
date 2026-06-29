"""FFT processor — high-resolution spectrum.

Computes a Hann-windowed rfft over the most recent ``window_seconds`` of the
rolling buffer for each EEG channel, then re-bins the magnitude spectrum into a
fixed number of bins (``n_bins``, default 128) spanning ``min_freq_hz`` ..
``max_freq_hz`` so the browser always receives a consistent, high-resolution
spectrum (spectrogram-style heatmap) regardless of sample rate or window length.

Throttled to ``update_hz`` so the payload stays small; between updates the
pipeline reuses the previous result.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor


class FFTProcessor(EEGProcessor):
    name = "fft"
    output_keys = ("fft",)
    # The spectrum defaults to the FILTERED window (reflects the global filter
    # chain); toggle input="raw" to see the full picture incl. line noise.
    default_input = "filtered"

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.window_seconds = float(self.opt("window_seconds", 2.0))
        self.update_hz = float(self.opt("update_hz", 15.0))
        self.n_bins = int(self.opt("n_bins", 128))
        self.min_freq_hz = float(self.opt("min_freq_hz", 0.0))
        self.max_freq_hz = float(self.opt("max_freq_hz", 64.0))
        self.max_channels = int(self.opt("max_channels", 64))
        self._sample_rate = 0.0
        self._last_emit_frame = -10_000
        self._window: np.ndarray | None = None
        self._window_n = 0

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        self.reset()

    def reset(self) -> None:
        # frame_index restarts at 0 on (re)configure (e.g. a stream switch); clear
        # the throttle baseline so the FFT doesn't freeze until it catches up.
        self._last_emit_frame = -10_000

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
        if state.frame_index - self._last_emit_frame < self._emit_interval(state):
            return {}
        self._last_emit_frame = state.frame_index

        segment = self.latest(state, self.window_seconds)  # (win_n, n_eeg)
        win_n = segment.shape[0]
        if win_n < 8 or segment.shape[1] == 0:
            return {}

        window = self._ensure_window(win_n)[:, None]
        spectrum = np.fft.rfft(segment * window, axis=0)
        mags = np.abs(spectrum) / win_n  # (n_freqs, n_eeg)
        freqs = np.fft.rfftfreq(win_n, d=1.0 / sr)

        # Re-bin into n_bins linearly-spaced bins spanning [min, max] (clamped to
        # Nyquist), averaging the FFT magnitudes that fall in each target bin.
        fmax = min(self.max_freq_hz, sr / 2.0)
        fmin = max(self.min_freq_hz, 0.0)
        edges = np.linspace(fmin, fmax, self.n_bins + 1)
        centers = 0.5 * (edges[:-1] + edges[1:])

        in_range = (freqs >= fmin) & (freqs <= fmax)
        bin_idx = np.clip(np.digitize(freqs[in_range], edges) - 1, 0, self.n_bins - 1)
        sel = mags[in_range, :]
        n_ch = min(sel.shape[1], self.max_channels)
        sel = sel[:, :n_ch]

        sums = np.zeros((self.n_bins, n_ch))
        np.add.at(sums, bin_idx, sel)
        counts = np.maximum(np.bincount(bin_idx, minlength=self.n_bins), 1)
        binned = sums / counts[:, None]  # (n_bins, n_ch)

        return {
            "fft": {
                "freqs": centers.astype(float).tolist(),
                "values": binned.T.astype(float).tolist(),  # values[channel][bin]
            }
        }

    def _emit_interval(self, state: ProcessingState) -> int:
        """Frames between emits, derived from the pipeline output rate."""
        output_hz = getattr(state, "_output_hz", None) or 30.0
        return max(1, int(round(output_hz / max(self.update_hz, 0.1))))
