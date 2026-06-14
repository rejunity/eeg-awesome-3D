"""Band power processor.

Computes delta/theta/alpha/beta/gamma band powers per EEG channel from a
Hann-windowed periodogram over the rolling window, then normalizes each band
to roughly [0, 1] across channels for stable visual display.

Bands are configurable. A known 10 Hz input should light up alpha; 20 Hz beta.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor

DEFAULT_BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}


class BandPowerProcessor(EEGProcessor):
    name = "band_power"
    output_keys = ("bands",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        raw_bands = self.opt("bands", None) or DEFAULT_BANDS
        self.bands: dict[str, tuple[float, float]] = {
            name: (float(lo), float(hi)) for name, (lo, hi) in raw_bands.items()
        }
        self._sample_rate = 0.0
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
        eeg = self.latest(state)  # whole window
        if sr <= 0 or eeg.shape[0] < 16 or eeg.shape[1] == 0:
            return {"bands": {name: [] for name in self.bands}}

        n = eeg.shape[0]
        window = self._ensure_window(n)[:, None]
        spectrum = np.fft.rfft(eeg * window, axis=0)
        psd = (np.abs(spectrum) ** 2) / n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)

        out: dict[str, list[float]] = {}
        for name, (lo, hi) in self.bands.items():
            mask = (freqs >= lo) & (freqs < hi)
            if not mask.any():
                out[name] = [0.0] * eeg.shape[1]
                continue
            power = psd[mask, :].mean(axis=0)  # (n_eeg,)
            # Log-compress then normalize across channels for display stability.
            comp = np.log1p(power)
            peak = comp.max()
            norm = comp / peak if peak > 0 else comp
            out[name] = norm.astype(float).tolist()

        return {"bands": out}
