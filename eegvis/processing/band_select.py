"""Runtime-selectable band processor.

Applied to the raw rolling buffer (before the browser's running-mean/SD
normalisation and colouring). When a band is selected, ``latest`` becomes the
per-channel amplitude in that frequency band (computed from a Hann-windowed
periodogram over the rolling window); when the band is ``None`` it passes the
raw last sample through unchanged.

The selected band is controlled at runtime from the UI (see Engine.set_band).
"""

from __future__ import annotations

import numpy as np

from ..models import EEGChunk, ProcessingState, StreamMetadata
from .base import EEGProcessor

BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}


class BandSelectProcessor(EEGProcessor):
    name = "band_select"
    output_keys = ("latest",)

    def __init__(self, band: str | None = None):
        super().__init__(enabled=True)
        self.band = band if band in BANDS else None
        self._sample_rate = 0.0
        self._window: np.ndarray | None = None
        self._window_n = 0

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate

    def set_band(self, band: str | None) -> None:
        self.band = band if band in BANDS else None

    def _hann(self, n: int) -> np.ndarray:
        if self._window is None or self._window_n != n:
            self._window = np.hanning(n)
            self._window_n = n
        return self._window

    def process(self, chunk: EEGChunk, state: ProcessingState) -> dict:
        eeg = self._eeg_view(state)  # (samples, n_eeg)
        if eeg.shape[0] == 0 or eeg.shape[1] == 0:
            return {}

        if self.band is None:
            return {"latest": eeg[-1, :].astype(float).tolist()}

        sr = state.sample_rate or self._sample_rate
        n = eeg.shape[0]
        if sr <= 0 or n < 16:
            return {"latest": eeg[-1, :].astype(float).tolist()}

        window = self._hann(n)[:, None]
        spectrum = np.fft.rfft(eeg * window, axis=0)
        psd = (np.abs(spectrum) ** 2) / n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)

        lo, hi = BANDS[self.band]
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            return {"latest": [0.0] * eeg.shape[1]}
        amplitude = np.sqrt(psd[mask, :].mean(axis=0))  # per-channel band amplitude
        return {"latest": amplitude.astype(float).tolist()}
