"""Runtime-selectable band processor.

Reads the sliding window (before the browser's running-mean/SD normalisation
and colouring). When a band is selected, ``latest`` becomes the per-channel
amplitude in that frequency band (Hann-windowed periodogram); when the band is
``None`` it passes the raw last sample through unchanged.

It picks how much of the window to use per band: lower bands need a longer span
(a few cycles of the lowest frequency) for adequate frequency resolution.

The selected band is controlled at runtime from the UI (see Engine.set_band).
"""

from __future__ import annotations

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor

BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}
# Cycles of the band's lowest frequency to include (sets the analysis span).
_CYCLES = 5.0


class BandSelectProcessor(EEGProcessor):
    name = "band_select"
    output_keys = ("latest",)

    def __init__(self, band: str | None = None):
        super().__init__(enabled=True)
        self.band = band if band in BANDS else None
        self._sample_rate = 0.0

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate

    def set_band(self, band: str | None) -> None:
        self.band = band if band in BANDS else None

    def process(self, state: ProcessingState) -> dict:
        if self.band is None:
            eeg = self.latest(state, None)
            if eeg.shape[0] == 0 or eeg.shape[1] == 0:
                return {}
            return {"latest": eeg[-1, :].astype(float).tolist()}

        sr = state.sample_rate or self._sample_rate
        lo, hi = BANDS[self.band]
        # Choose the span from the band: a few cycles of the lowest frequency.
        seconds = _CYCLES / lo
        eeg = self.latest(state, seconds)  # (n, n_eeg)
        n = eeg.shape[0]
        if sr <= 0 or n < 16 or eeg.shape[1] == 0:
            return {"latest": eeg[-1, :].astype(float).tolist()} if n else {}

        spectrum = np.fft.rfft(eeg * np.hanning(n)[:, None], axis=0)
        psd = (np.abs(spectrum) ** 2) / n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)

        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            return {"latest": [0.0] * eeg.shape[1]}
        amplitude = np.sqrt(psd[mask, :].mean(axis=0))  # per-channel band amplitude
        return {"latest": amplitude.astype(float).tolist()}
