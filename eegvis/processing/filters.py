"""Preprocessing filters: band-pass, notch and common-average reference.

These transform the signal *in place* in the rolling buffer so that feature
extractors downstream (FFT, band power, Hjorth, …) operate on the cleaned data.
Place them before the extractors in the ``processors`` config list.

Band-pass and notch are temporal IIR filters (SciPy second-order sections) that
keep ``zi`` state across runs, so each new sample is filtered exactly once and
the result is independent of the global run cadence (a throttled run just
filters a larger batch). CAR is a per-sample spatial operation (subtract the
cross-channel mean) and keeps no state.

They declare no output keys of their own.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal as sp_signal

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor


def _write_back(state: ProcessingState, y: np.ndarray, idx: list[int]) -> None:
    """Write filtered samples ``y`` (n, n_eeg) back into the buffer's EEG cols."""
    n = y.shape[0]
    if n and n <= state.rolling_data.shape[0]:
        for col, ch in enumerate(idx):
            state.rolling_data[-n:, ch] = y[:, col]


class _SOSFilterProcessor(EEGProcessor):
    """Shared stateful SOS filtering over the samples added since the last run."""

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self._sos: np.ndarray | None = None
        self._zi: np.ndarray | None = None  # shape (n_sections, 2, n_channels)
        self._sample_rate = 0.0

    def _design(self, sample_rate: float) -> np.ndarray:
        raise NotImplementedError

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        if self._sample_rate > 0:
            self._sos = self._design(self._sample_rate)
        self.reset()

    def reset(self) -> None:
        self._zi = None

    def process(self, state: ProcessingState) -> dict[str, Any]:
        x = self.new_since_run(state).astype(np.float64)  # (n, n_eeg)
        if self._sos is None or x.shape[0] == 0:
            return {}
        idx = state.eeg_channel_indices or list(range(state.rolling_data.shape[1]))
        n_ch = x.shape[1]

        # sosfilt wants zi shaped (n_sections, 2, n_channels). Seed it from the
        # first sample so the very first output starts settled, not from zero.
        if self._zi is None or self._zi.shape[2] != n_ch:
            zi0 = sp_signal.sosfilt_zi(self._sos)  # (n_sections, 2)
            self._zi = np.repeat(zi0[:, :, None], n_ch, axis=2) * x[0, :][None, None, :]

        y, self._zi = sp_signal.sosfilt(self._sos, x, axis=0, zi=self._zi)
        _write_back(state, y, idx)
        return {}


class BandpassProcessor(_SOSFilterProcessor):
    name = "bandpass"
    output_keys = ()

    def _design(self, sample_rate: float) -> np.ndarray:
        low = max(float(self.opt("low_hz", 1.0)), 0.01)
        high = float(self.opt("high_hz", 45.0))
        order = int(self.opt("order", 4))
        nyq = sample_rate / 2.0
        high = min(high, nyq * 0.99)
        return sp_signal.butter(
            order, [low / nyq, high / nyq], btype="bandpass", output="sos"
        )


class NotchProcessor(_SOSFilterProcessor):
    name = "notch"
    output_keys = ()

    def _design(self, sample_rate: float) -> np.ndarray:
        freq = float(self.opt("hz", 50.0))
        quality = float(self.opt("quality", 30.0))
        b, a = sp_signal.iirnotch(freq, quality, sample_rate)
        return sp_signal.tf2sos(b, a)


class CARProcessor(EEGProcessor):
    """Common Average Reference: subtract the per-sample mean across EEG channels."""

    name = "car"
    output_keys = ()

    def process(self, state: ProcessingState) -> dict[str, Any]:
        x = self.new_since_run(state).astype(np.float64)  # (n, n_eeg)
        if x.shape[0] == 0 or x.shape[1] == 0:
            return {}
        idx = state.eeg_channel_indices or list(range(state.rolling_data.shape[1]))
        y = x - x.mean(axis=1, keepdims=True)
        _write_back(state, y, idx)
        return {}
