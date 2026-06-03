"""Bandpass and notch filters with preserved realtime state.

Both use SciPy second-order sections (SOS) and ``sosfilt`` with retained
``zi`` state, so each incoming chunk continues the filter rather than
recomputing from scratch. State is kept per (EEG) channel.

These processors filter the rolling buffer in place via ``state`` so that
downstream processors (FFT, band power) see filtered data. They declare no
output keys of their own.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal as sp_signal

from ..models import EEGChunk, ProcessingState, StreamMetadata
from .base import EEGProcessor


class _SOSFilterProcessor(EEGProcessor):
    """Shared SOS realtime filtering against the latest chunk."""

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self._sos: np.ndarray | None = None
        self._zi: np.ndarray | None = None  # shape (n_sections, 2, n_channels)
        self._sample_rate = 0.0
        self._eeg_indices: list[int] = []

    def _design(self, sample_rate: float) -> np.ndarray:
        raise NotImplementedError

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        self._eeg_indices = metadata.eeg_channel_indices()
        if self._sample_rate > 0:
            self._sos = self._design(self._sample_rate)
        self.reset()

    def reset(self) -> None:
        self._zi = None

    def process(self, chunk: EEGChunk, state: ProcessingState) -> dict[str, Any]:
        if self._sos is None or chunk.data.shape[0] == 0:
            return {}
        idx = self._eeg_indices or list(range(chunk.data.shape[1]))
        x = chunk.data[:, idx].astype(np.float64)  # (samples, n_eeg)
        n_ch = x.shape[1]

        # For axis=0 input (samples, channels), sosfilt wants zi shaped
        # (n_sections, 2, n_channels). sosfilt_zi gives (n_sections, 2).
        if self._zi is None or self._zi.shape[2] != n_ch:
            zi0 = sp_signal.sosfilt_zi(self._sos)  # (n_sections, 2)
            self._zi = np.repeat(zi0[:, :, None], n_ch, axis=2)
            # Scale steady-state zi by the first sample so output starts settled.
            self._zi = self._zi * x[0, :][None, None, :]

        # Filter along time (axis 0) per channel.
        y, self._zi = sp_signal.sosfilt(self._sos, x, axis=0, zi=self._zi)

        # Write filtered samples back into the rolling buffer's EEG columns so
        # downstream processors operate on filtered data. The most recent
        # ``samples`` rows of the rolling buffer correspond to this chunk.
        n = y.shape[0]
        if n <= state.rolling_data.shape[0]:
            for col, ch in enumerate(idx):
                state.rolling_data[-n:, ch] = y[:, col]
        return {}


class BandpassProcessor(_SOSFilterProcessor):
    name = "bandpass"
    output_keys = ()

    def _design(self, sample_rate: float) -> np.ndarray:
        low = float(self.opt("low_hz", 1.0))
        high = float(self.opt("high_hz", 45.0))
        order = int(self.opt("order", 4))
        nyq = sample_rate / 2.0
        high = min(high, nyq * 0.99)
        low = max(low, 0.01)
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
