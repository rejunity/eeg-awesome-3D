"""Hilbert band envelope.

For each EEG band, band-pass filters the rolling window and takes the analytic
(Hilbert) amplitude envelope, reporting the mean envelope per channel. Unlike a
band-power periodogram this is an amplitude-domain measure of the band's
instantaneous activity. Emitted as per-channel features ``env_<band>``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal as sp_signal

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor

BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}


class BandEnvelopeProcessor(EEGProcessor):
    name = "band_envelope"
    output_keys = ("features",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.window_seconds = float(self.opt("window_seconds", 2.0))
        sel = self.opt("bands", None)
        self.bands = {k: BANDS[k] for k in sel} if sel else dict(BANDS)
        self._sample_rate = 0.0
        self._sos: dict[str, np.ndarray] = {}

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        self._sos = {}
        nyq = self._sample_rate / 2.0
        if nyq <= 0:
            return
        for name, (lo, hi) in self.bands.items():
            self._sos[name] = sp_signal.butter(
                4, [max(lo, 0.1) / nyq, min(hi, nyq * 0.99) / nyq],
                btype="bandpass", output="sos",
            )

    def process(self, state: ProcessingState) -> dict[str, Any]:
        x = self.latest(state, self.window_seconds).astype(np.float64)  # (n, n_eeg)
        if x.shape[0] < 16 or x.shape[1] == 0 or not self._sos:
            return {}
        features: dict[str, list[float]] = {}
        for name, sos in self._sos.items():
            filtered = sp_signal.sosfilt(sos, x, axis=0)
            envelope = np.abs(sp_signal.hilbert(filtered, axis=0))
            features[f"env_{name}"] = envelope.mean(axis=0).astype(float).tolist()
        return {"features": features}
