"""Smoothing processor.

Exponential smoothing of the ``normalized`` per-channel values for visual
stability (the browser scale/colour shouldn't jitter at the sample level).
Runs after normalization and rewrites ``normalized`` in the frame outputs.

    smoothed = alpha * new + (1 - alpha) * smoothed
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import EEGChunk, ProcessingState, StreamMetadata
from .base import EEGProcessor


class SmoothingProcessor(EEGProcessor):
    name = "smoothing"
    output_keys = ("normalized",)
    # Reads prior processor output from the shared frame outputs.
    reads_keys = ("normalized",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.alpha = float(self.opt("alpha", 0.25))
        self._state: np.ndarray | None = None

    def reset(self) -> None:
        self._state = None

    def process(self, chunk: EEGChunk, state: ProcessingState) -> dict[str, Any]:
        # Smoothing consumes the current frame's normalized output; the pipeline
        # passes accumulated outputs via state._frame_outputs.
        outputs = getattr(state, "_frame_outputs", {})
        values = outputs.get("normalized")
        if not values:
            return {}
        arr = np.asarray(values, dtype=np.float64)
        if self._state is None or self._state.shape != arr.shape:
            self._state = arr.copy()
        else:
            self._state = self.alpha * arr + (1.0 - self.alpha) * self._state
        return {"normalized": self._state.astype(float).tolist()}
