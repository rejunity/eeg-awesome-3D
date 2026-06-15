"""Preprocessing filters: band-pass, notch and common-average reference.

These form the global FILTER CHAIN: an ordered, stateful front-end that runs
every tick and transforms the raw signal into the ``filtered`` window. Feature
extractors then read that filtered window (a pure fan-out), so the chain is the
only place ordering matters, and the raw window is never destroyed (the raw
trace/electrodes keep using it).

Band-pass and notch are temporal IIR filters (SciPy second-order sections) that
keep ``zi`` state across ticks, so each new sample is filtered exactly once.
CAR is a per-sample spatial operation (subtract the cross-channel mean). The
chain composes: each filter reads and rewrites the filtered window in turn.

They declare no output keys of their own.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal as sp_signal

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor


def _write_back(state: ProcessingState, y: np.ndarray, idx: list[int]) -> None:
    """Write filtered samples ``y`` (n, n_eeg) into the filtered window's EEG cols."""
    buf = state.filtered_data
    if buf is None:
        return
    n = y.shape[0]
    if n and n <= buf.shape[0]:
        for col, ch in enumerate(idx):
            buf[-n:, ch] = y[:, col]


class _SOSFilterProcessor(EEGProcessor):
    """Shared stateful SOS filtering of the new samples on the filtered window."""

    # Filters read and rewrite the filtered window so the chain composes.
    default_input = "filtered"

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self._sos: np.ndarray | None = None
        self._zi: np.ndarray | None = None  # shape (n_sections, 2, n_channels)
        self._sample_rate = 0.0

    def _design(self, sample_rate: float) -> np.ndarray | None:
        raise NotImplementedError

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        self._redesign()
        self.reset()

    def _redesign(self) -> None:
        self._sos = self._design(self._sample_rate) if self._sample_rate > 0 else None
        self._zi = None

    def reset(self) -> None:
        self._zi = None

    def process(self, state: ProcessingState) -> dict[str, Any]:
        x = self.new_samples(state).astype(np.float64)  # (n, n_eeg) on filtered buf
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

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.low_hz = float(self.opt("low_hz", 1.0))
        self.high_hz = float(self.opt("high_hz", 45.0))
        self.order = int(self.opt("order", 4))

    def _design(self, sample_rate: float) -> np.ndarray | None:
        nyq = sample_rate / 2.0
        lo = max(min(self.low_hz, self.high_hz), 0.01)
        hi = min(max(self.low_hz, self.high_hz), nyq * 0.99)
        if hi <= lo:
            return None
        # low < high -> keep the band (pass); low > high -> reject it (stop).
        btype = "bandstop" if self.low_hz > self.high_hz else "bandpass"
        return sp_signal.butter(
            self.order, [lo / nyq, hi / nyq], btype=btype, output="sos"
        )

    def set_band(self, low_hz: float, high_hz: float) -> None:
        """Retune at runtime. low < high passes the band; low > high rejects it."""
        self.low_hz = float(low_hz)
        self.high_hz = float(high_hz)
        self._redesign()


class NotchProcessor(_SOSFilterProcessor):
    name = "notch"
    output_keys = ()

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.hz = float(self.opt("hz", 50.0))
        self.quality = float(self.opt("quality", 30.0))

    def _design(self, sample_rate: float) -> np.ndarray | None:
        if self.hz <= 0 or self.hz >= sample_rate / 2.0:
            return None
        b, a = sp_signal.iirnotch(self.hz, self.quality, sample_rate)
        return sp_signal.tf2sos(b, a)

    def set_freq(self, hz: float) -> None:
        """Retune the notch frequency at runtime (e.g. 50 <-> 60 Hz)."""
        self.hz = float(hz)
        self._redesign()


class CARProcessor(EEGProcessor):
    """Common Average Reference: subtract the per-sample mean across EEG channels."""

    name = "car"
    output_keys = ()
    default_input = "filtered"

    def process(self, state: ProcessingState) -> dict[str, Any]:
        x = self.new_samples(state).astype(np.float64)  # (n, n_eeg) on filtered buf
        if x.shape[0] == 0 or x.shape[1] == 0:
            return {}
        idx = state.eeg_channel_indices or list(range(state.rolling_data.shape[1]))
        y = x - x.mean(axis=1, keepdims=True)
        _write_back(state, y, idx)
        return {}
