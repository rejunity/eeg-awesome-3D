"""Runtime-selectable band processor.

Reads the sliding window (before the browser's running-mean/SD normalisation
and colouring). Three run rates (set from the UI):

- "per-sample": a stateful band-pass filter is applied to every new sample, so
  the output is a continuous per-sample stream (``band_samples``) that the
  browser plays back through its resampler at the full source resolution — the
  band trace then matches the raw trace's speed/smoothness.
- "realtime" / "frequency": a Hann-windowed periodogram gives a single
  per-channel band *amplitude* (``latest``), recomputed on each new chunk or at
  run_hz; the browser eases it to avoid stepped transitions.

When the band is ``None`` it passes the raw last sample through unchanged.
"""

from __future__ import annotations

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
# Cycles of the band's lowest frequency to include in the windowed estimate.
_CYCLES = 5.0


class BandSelectProcessor(EEGProcessor):
    name = "band_select"
    output_keys = ("latest", "band_samples")

    def __init__(self, band: str | None = None):
        super().__init__(enabled=True)
        self.band = band if band in BANDS else None
        self._sample_rate = 0.0
        self._latest: list[float] | None = None  # cached windowed amplitude
        self._sos: np.ndarray | None = None  # per-sample band-pass
        self._zi: np.ndarray | None = None

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        self._design()
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._zi = None
        self._latest = None

    def set_band(self, band: str | None) -> None:
        self.band = band if band in BANDS else None
        self._design()
        self._zi = None
        self._latest = None

    def _design(self) -> None:
        sr = self._sample_rate
        if self.band is None or sr <= 0:
            self._sos = None
            return
        lo, hi = BANDS[self.band]
        nyq = sr / 2.0
        self._sos = sp_signal.butter(
            4, [max(lo, 0.1) / nyq, min(hi, nyq * 0.99) / nyq],
            btype="bandpass", output="sos",
        )

    # The pipeline calls run(); band_select manages its own cadence (including
    # the streaming per-sample mode), so it overrides run() rather than process.
    def run(self, state: ProcessingState, now: float, has_new_data: bool) -> dict:
        if self.band is None:
            eeg = self.latest(state)
            return {"latest": eeg[-1, :].astype(float).tolist()} if eeg.shape[0] else {}

        if self.run_mode == "per-sample":
            return self._per_sample(state)

        # Windowed amplitude, recomputed per cadence; reused between runs.
        if self.run_mode == "frequency":
            due = (now - self._last_run_t) >= (1.0 / max(self.run_hz, 0.01))
        else:  # realtime
            due = has_new_data
        if due:
            self._last_run_t = now
            amp = self._windowed(state)
            if amp is not None:
                self._latest = amp
        return {"latest": self._latest} if self._latest is not None else {}

    def process(self, state: ProcessingState) -> dict:  # unused; run() is the entry
        return self.run(state, self._last_run_t, True)

    def _per_sample(self, state: ProcessingState) -> dict:
        x = self.new_samples(state).astype(np.float64)  # (n_new, n_eeg)
        if self._sos is None or x.shape[0] == 0:
            return {}
        n_ch = x.shape[1]
        if self._zi is None or self._zi.shape[2] != n_ch:
            zi0 = sp_signal.sosfilt_zi(self._sos)  # (n_sections, 2)
            self._zi = np.repeat(zi0[:, :, None], n_ch, axis=2) * x[0, :][None, None, :]
        y, self._zi = sp_signal.sosfilt(self._sos, x, axis=0, zi=self._zi)
        return {"band_samples": y.astype(float).tolist(), "latest": y[-1, :].astype(float).tolist()}

    def _windowed(self, state: ProcessingState) -> list[float] | None:
        sr = state.sample_rate or self._sample_rate
        lo, hi = BANDS[self.band]
        eeg = self.latest(state, _CYCLES / lo)  # span scales with the band
        n = eeg.shape[0]
        if sr <= 0 or n < 16 or eeg.shape[1] == 0:
            return None
        spectrum = np.fft.rfft(eeg * np.hanning(n)[:, None], axis=0)
        psd = (np.abs(spectrum) ** 2) / n
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            return [0.0] * eeg.shape[1]
        return np.sqrt(psd[mask, :].mean(axis=0)).astype(float).tolist()
