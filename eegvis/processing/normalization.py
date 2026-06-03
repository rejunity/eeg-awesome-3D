"""Normalization processor.

Recreates the Unity moving min/max normalization and adds an optional z-score
mode. Output ``normalized`` is per-channel in roughly [-1, 1] (centered),
suitable for direct colour/scale animation in the browser.

Unity reference (LSLInletReader.cs):
    channels_max = Lerp(channels_max, max(channels_max, x), reactivity)
    eeg = InverseLerp(min, max, x)               # -> [0, 1]
    eeg = (eeg - expected_mean) / expected_variance   # -> centered ~[-1, 1]
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import EEGChunk, ProcessingState, StreamMetadata
from .base import EEGProcessor


class NormalizationProcessor(EEGProcessor):
    name = "normalization"
    output_keys = ("normalized", "latest")

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.method = self.opt("method", "moving_minmax")
        self.reactivity = float(self.opt("reactivity", 0.9))
        self.expected_mean = float(self.opt("expected_mean", 0.5))
        self.expected_variance = float(self.opt("expected_variance", 0.25))
        self._min: np.ndarray | None = None
        self._max: np.ndarray | None = None
        self._n_channels = 0

    def configure(self, metadata: StreamMetadata) -> None:
        # Track stats over EEG channels only.
        n = len(metadata.eeg_channel_indices())
        self._n_channels = n
        self.reset()

    def reset(self) -> None:
        self._min = np.full(self._n_channels, np.inf)
        self._max = np.full(self._n_channels, -np.inf)

    def process(self, chunk: EEGChunk, state: ProcessingState) -> dict[str, Any]:
        eeg = self._eeg_view(state)  # (samples, n_eeg)
        if eeg.shape[0] == 0 or eeg.shape[1] == 0:
            return {"normalized": [], "latest": []}

        if self._min is None or self._min.shape[0] != eeg.shape[1]:
            self._n_channels = eeg.shape[1]
            self.reset()

        latest = eeg[-1, :]

        if self.method == "zscore":
            normalized = self._zscore(eeg, latest)
        else:
            normalized = self._moving_minmax(eeg, latest)

        return {
            "normalized": normalized.astype(float).tolist(),
            "latest": latest.astype(float).tolist(),
        }

    def _moving_minmax(self, eeg: np.ndarray, latest: np.ndarray) -> np.ndarray:
        chunk_min = eeg.min(axis=0)
        chunk_max = eeg.max(axis=0)

        # First observation: snap; afterwards exponentially track toward extremes.
        first = ~np.isfinite(self._min)
        prev_min = np.where(first, chunk_min, self._min)  # avoid inf arithmetic
        prev_max = np.where(first, chunk_max, self._max)
        self._min = self._lerp(prev_min, np.minimum(prev_min, chunk_min))
        self._max = self._lerp(prev_max, np.maximum(prev_max, chunk_max))

        span = np.maximum(self._max - self._min, 1e-9)
        # InverseLerp -> [0, 1]
        norm01 = np.clip((latest - self._min) / span, 0.0, 1.0)
        # Center like Unity: (v - mean) / variance -> roughly [-1, 1]
        centered = (norm01 - self.expected_mean) / self.expected_variance
        return np.clip(centered, -1.0, 1.0)

    def _lerp(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a + (b - a) * self.reactivity

    def _zscore(self, eeg: np.ndarray, latest: np.ndarray) -> np.ndarray:
        mean = eeg.mean(axis=0)
        std = np.maximum(eeg.std(axis=0), 1e-9)
        z = (latest - mean) / std
        # Squash to [-1, 1] so display code can treat both modes the same.
        return np.tanh(z / 3.0)
