"""Spectral entropy.

Shannon entropy of the normalised power spectrum per EEG channel, in [0, 1]
(1 = flat/white spectrum, 0 = all power in one bin). A compact measure of
spectral complexity/flatness. Emitted as the per-channel feature
``spectral_entropy``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor


class SpectralEntropyProcessor(EEGProcessor):
    name = "spectral_entropy"
    output_keys = ("features",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.window_seconds = float(self.opt("window_seconds", 2.0))
        self.min_freq_hz = float(self.opt("min_freq_hz", 1.0))
        self.max_freq_hz = float(self.opt("max_freq_hz", 45.0))
        self._sample_rate = 0.0

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate

    def process(self, state: ProcessingState) -> dict[str, Any]:
        sr = state.sample_rate or self._sample_rate
        x = self.latest(state, self.window_seconds).astype(np.float64)  # (n, n_eeg)
        n = x.shape[0]
        if sr <= 0 or n < 16 or x.shape[1] == 0:
            return {}
        spectrum = np.fft.rfft(x * np.hanning(n)[:, None], axis=0)
        psd = (np.abs(spectrum) ** 2) / n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        mask = (freqs >= self.min_freq_hz) & (freqs <= self.max_freq_hz)
        if not mask.any():
            return {}
        psd = psd[mask, :]
        total = np.maximum(psd.sum(axis=0, keepdims=True), 1e-20)
        p = psd / total
        ent = -np.sum(p * np.log(p + 1e-20), axis=0) / np.log(p.shape[0])
        return {"features": {"spectral_entropy": ent.astype(float).tolist()}}
