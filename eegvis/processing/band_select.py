"""Runtime-selectable band processor.

Operates purely on the GLOBAL sliding window of the latest N samples
(``ProcessingState.rolling_data`` — the single source of truth, kept current by
the pipeline). The processor is a pure function of that window: every run it
reads the most recent span it needs (``latest(state, seconds)``) and band-pass
filters it from scratch — no streaming / per-processor filter state. The result
is therefore independent of how often the processor is executed.

Filter rate (how often it runs / what it emits):

- "per-sample": emit the filtered value for every sample appended to the window
  since the last run (``band_samples``) — a continuous stream the browser plays
  back at the raw-trace speed.
- "realtime" / "frequency": emit a single per-channel band *amplitude* (RMS of
  the filtered window) on each new chunk / at run_hz; the browser eases it.

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
        self._latest: list[float] | None = None  # cached windowed amplitude
        self._sos: np.ndarray | None = None

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        self._design()
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._latest = None

    def set_band(self, band: str | None) -> None:
        self.band = band if band in BANDS else None
        self._design()
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

    def _span_seconds(self) -> float:
        # Enough of the window for the filter to settle for the band's lowest
        # frequency: the oldest part of the span carries the start-up transient,
        # the recent samples we actually use/emit are settled. latest() clamps
        # this to whatever the global window currently holds.
        lo, _ = BANDS[self.band]  # type: ignore[index]
        return max(2.0, 8.0 / lo)

    # The pipeline calls run(); band_select reads the global window directly and
    # manages its own cadence, so it overrides run() rather than process().
    def run(self, state: ProcessingState, now: float, has_new_data: bool) -> dict:
        if self.band is None:
            eeg = self.latest(state)
            return {"latest": eeg[-1, :].astype(float).tolist()} if eeg.shape[0] else {}
        if self._sos is None:
            return {}

        win = self.latest(state, self._span_seconds())  # latest span of the window
        if win.shape[0] < 16 or win.shape[1] == 0:
            return {}
        # Band-pass the window from scratch (stateless) — a pure function of the
        # window, so the result does not depend on the execution frequency.
        filtered = sp_signal.sosfilt(self._sos, win.astype(np.float64), axis=0)

        if self.run_mode == "per-sample":
            # Emit the filtered value for each sample the window gained this tick.
            m = min(state.last_appended, filtered.shape[0])
            if m == 0:
                return {}
            return {
                "band_samples": filtered[-m:, :].astype(float).tolist(),
                "latest": filtered[-1, :].astype(float).tolist(),
            }

        # Windowed amplitude (RMS of the band-filtered window), per cadence.
        if self.run_mode == "frequency":
            due = (now - self._last_run_t) >= (1.0 / max(self.run_hz, 0.01))
        else:  # realtime
            due = has_new_data
        if due:
            self._last_run_t = now
            self._latest = np.sqrt(np.mean(filtered**2, axis=0)).astype(float).tolist()
        return {"latest": self._latest} if self._latest is not None else {}

    def process(self, state: ProcessingState) -> dict:  # unused; run() is the entry
        return self.run(state, self._last_run_t, True)
