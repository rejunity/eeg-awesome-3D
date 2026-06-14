"""Line length.

Mean absolute sample-to-sample difference per EEG channel over the rolling
window — a cheap measure of signal activity/roughness, popular in seizure and
burst detection. Emitted as the per-channel feature ``line_length``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState
from .base import EEGProcessor


class LineLengthProcessor(EEGProcessor):
    name = "line_length"
    output_keys = ("features",)

    def process(self, state: ProcessingState) -> dict[str, Any]:
        x = self.latest(state).astype(np.float64)  # (n, n_eeg)
        if x.shape[0] < 2 or x.shape[1] == 0:
            return {}
        ll = np.mean(np.abs(np.diff(x, axis=0)), axis=0)
        return {"features": {"line_length": ll.astype(float).tolist()}}
