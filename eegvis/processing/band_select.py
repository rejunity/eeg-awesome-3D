"""Runtime-selectable band processor.

Operates purely on the GLOBAL sliding window of the latest N samples
(``ProcessingState.rolling_data`` — the single source of truth, kept current by
the pipeline). The processor is a pure function of that window: every run it
reads the most recent span it needs (``latest(state, seconds)``) and band-pass
filters it from scratch — no streaming / per-processor filter state. The result
is therefore independent of how often the processor is executed.

Every filter rate emits the SAME quantity — the band-pass filtered signal
(``band_samples``, one per-channel value per sample). The rate only controls how
often / in how large a batch those samples are delivered, never their values:

- "realtime" / "per-sample": emit the filtered value for every sample the window
  gained this tick.
- "frequency": accumulate and emit the filtered values for all samples since the
  last emit, run_hz times per second (larger batches, identical values).

Because the filter is applied to the global window from scratch each run, the
filtered value at a given sample is the same regardless of the rate (once that
sample has settled), so the rendered traces match across rates. ``latest`` also
carries the per-channel RMS of the filtered window as a stable amplitude.

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


class BandSelectProcessor(EEGProcessor):
    name = "band_select"
    output_keys = ("latest", "band_samples")

    def __init__(self, band: str | None = None):
        super().__init__(enabled=True)
        self.band = band if band in BANDS else None
        self._sample_rate = 0.0
        self._sos: np.ndarray | None = None
        self._pending = 0  # samples awaiting emission in "frequency" mode

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        self._design()
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._pending = 0

    def set_band(self, band: str | None) -> None:
        self.band = band if band in BANDS else None
        self._design()
        self._pending = 0

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

    # The pipeline calls run(); band_select reads the global window directly and
    # manages its own cadence, so it overrides run() rather than process().
    def run(self, state: ProcessingState, now: float, has_new_data: bool) -> dict:
        if self.band is None:
            eeg = self.latest(state)
            return {"latest": eeg[-1, :].astype(float).tolist()} if eeg.shape[0] else {}
        if self._sos is None:
            return {}

        # Band-pass the whole global window from scratch (stateless). The recent
        # samples we emit are far from the start-up transient and thus settled,
        # so their filtered values are independent of how often we run.
        win = self.latest(state)
        if win.shape[0] < 16 or win.shape[1] == 0:
            return {}
        filtered = sp_signal.sosfilt(self._sos, win.astype(np.float64), axis=0)
        rms = np.sqrt(np.mean(filtered**2, axis=0)).astype(float).tolist()

        # How many of the most-recent filtered samples to emit this tick.
        if self.run_mode == "frequency":
            self._pending += state.last_appended
            if (now - self._last_run_t) < (1.0 / max(self.run_hz, 0.01)):
                return {"latest": rms}  # not due yet; keep accumulating
            self._last_run_t = now
            m = self._pending
            self._pending = 0
        else:  # realtime / per-sample -> emit this tick's new samples
            m = state.last_appended

        m = min(m, filtered.shape[0])
        out: dict = {"latest": rms}
        if m > 0:
            out["band_samples"] = filtered[-m:, :].astype(float).tolist()
        return out

    def process(self, state: ProcessingState) -> dict:  # unused; run() is the entry
        return self.run(state, self._last_run_t, True)
