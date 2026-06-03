"""Short-Fourier visual parity processor.

Recreates the "short Fourier" visual feel from the Unity ``LSLInletReader.cs``:
for each EEG channel, three leaky complex oscillators at ~10 Hz, 20 Hz and 40 Hz
accumulate the normalized signal and report their magnitude. This is a visual
parity effect, not a scientific transform.

Unity per-sample update (mirrored here):
    eeg = (InverseLerp(min, max, x) - mean) / variance
    reA = reA * reactivity + eeg * cos(t * f * 2pi)
    imA = imA * reactivity + eeg * sin(t * f * 2pi)
    colorA = multiplier * sqrt(reA^2 + imA^2)
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..models import EEGChunk, ProcessingState, StreamMetadata
from .base import EEGProcessor


class ShortFourierVisualProcessor(EEGProcessor):
    name = "short_fourier"
    output_keys = ("short_fourier",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.reactivity = float(self.opt("reactivity", 0.1))
        self.multiplier = float(self.opt("multiplier", 1.0))
        self.frequencies = [float(f) for f in (self.opt("frequencies", [10, 20, 40]))]
        self.expected_mean = float(self.opt("expected_mean", 0.5))
        self.expected_variance = float(self.opt("expected_variance", 0.25))
        self._re: np.ndarray | None = None  # (n_bands, n_eeg)
        self._im: np.ndarray | None = None
        self._n_ch = 0

    def reset(self) -> None:
        self._re = None
        self._im = None

    def _ensure_state(self, n_ch: int) -> None:
        nb = len(self.frequencies)
        if self._re is None or self._n_ch != n_ch:
            self._n_ch = n_ch
            self._re = np.zeros((nb, n_ch))
            self._im = np.zeros((nb, n_ch))

    def process(self, chunk: EEGChunk, state: ProcessingState) -> dict[str, Any]:
        if chunk.data.shape[0] == 0:
            return self._emit()

        idx = state.eeg_channel_indices or list(range(chunk.data.shape[1]))
        x = chunk.data[:, idx].astype(np.float64)  # (samples, n_eeg)
        n_ch = x.shape[1]
        if n_ch == 0:
            return {"short_fourier": {}}
        self._ensure_state(n_ch)

        # Normalize each sample against the rolling-window extremes (cheap, local).
        eeg_win = state.rolling_data[:, idx]
        mn = eeg_win.min(axis=0)
        mx = np.maximum(eeg_win.max(axis=0), mn + 1e-9)
        norm = (x - mn) / (mx - mn)  # ~[0, 1]
        norm = (norm - self.expected_mean) / self.expected_variance  # centered

        t = chunk.timestamps  # (samples,)
        # Leaky accumulation, applied sample-by-sample to match Unity's recurrence.
        for s in range(norm.shape[0]):
            eeg = norm[s, :]  # (n_eeg,)
            ts = t[s]
            for b, f in enumerate(self.frequencies):
                ang = ts * f * 2.0 * math.pi
                self._re[b] = self._re[b] * self.reactivity + eeg * math.cos(ang)
                self._im[b] = self._im[b] * self.reactivity + eeg * math.sin(ang)

        return self._emit()

    def _emit(self) -> dict[str, Any]:
        if self._re is None:
            return {"short_fourier": {}}
        out: dict[str, list[float]] = {}
        for b, f in enumerate(self.frequencies):
            mag = self.multiplier * np.sqrt(self._re[b] ** 2 + self._im[b] ** 2)
            out[f"{int(f)}hz"] = mag.astype(float).tolist()
        return {"short_fourier": out}
