"""Aperiodic 1/f component.

Fits a line to the log-log power spectrum (log10 power vs log10 frequency) per
EEG channel over a fit range, FOOOF/specparam-style. The slope (typically
negative, the "1/f exponent") and offset summarise the aperiodic background that
underlies the oscillatory peaks. Emitted as per-channel features
``aperiodic_slope`` and ``aperiodic_offset``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor


class AperiodicProcessor(EEGProcessor):
    name = "aperiodic"
    output_keys = ("features",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.window_seconds = float(self.opt("window_seconds", 4.0))
        self.min_freq_hz = float(self.opt("min_freq_hz", 2.0))
        self.max_freq_hz = float(self.opt("max_freq_hz", 40.0))
        self._sample_rate = 0.0

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate

    def process(self, state: ProcessingState) -> dict[str, Any]:
        sr = state.sample_rate or self._sample_rate
        x = self.latest(state, self.window_seconds).astype(np.float64)  # (n, n_eeg)
        n = x.shape[0]
        if sr <= 0 or n < 32 or x.shape[1] == 0:
            return {}
        spectrum = np.fft.rfft(x * np.hanning(n)[:, None], axis=0)
        psd = (np.abs(spectrum) ** 2) / n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        mask = (freqs >= self.min_freq_hz) & (freqs <= self.max_freq_hz) & (freqs > 0)
        if mask.sum() < 4:
            return {}

        logf = np.log10(freqs[mask])  # (k,)
        logp = np.log10(psd[mask, :] + 1e-20)  # (k, n_eeg)
        # Per-channel least-squares slope/intercept of logp ~ slope*logf + offset.
        fc = logf - logf.mean()
        denom = np.sum(fc * fc)
        if denom <= 0:
            return {}
        slope = (fc[:, None] * (logp - logp.mean(axis=0))).sum(axis=0) / denom
        offset = logp.mean(axis=0) - slope * logf.mean()
        return {
            "features": {
                "aperiodic_slope": slope.astype(float).tolist(),
                "aperiodic_offset": offset.astype(float).tolist(),
            }
        }
