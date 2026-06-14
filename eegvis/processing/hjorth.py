"""Hjorth parameters.

Three cheap time-domain descriptors per EEG channel, computed over the rolling
window (Hjorth, 1970):

- Activity   = var(x)                       (signal power)
- Mobility   = sqrt(var(x') / var(x))       (mean frequency)
- Complexity = Mobility(x') / Mobility(x)   (bandwidth / shape)

Emitted as per-channel features ``hjorth_activity|mobility|complexity``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState
from .base import EEGProcessor


def _mobility(x: np.ndarray) -> np.ndarray:
    var = np.var(x, axis=0)
    dvar = np.var(np.diff(x, axis=0), axis=0)
    return np.sqrt(np.divide(dvar, var, out=np.zeros_like(var), where=var > 0))


class HjorthProcessor(EEGProcessor):
    name = "hjorth"
    output_keys = ("features",)

    def process(self, state: ProcessingState) -> dict[str, Any]:
        x = self.latest(state).astype(np.float64)  # (n, n_eeg)
        if x.shape[0] < 4 or x.shape[1] == 0:
            return {}
        activity = np.var(x, axis=0)
        mob = _mobility(x)
        mob_d = _mobility(np.diff(x, axis=0))
        complexity = np.divide(mob_d, mob, out=np.zeros_like(mob), where=mob > 0)
        return {
            "features": {
                "hjorth_activity": activity.astype(float).tolist(),
                "hjorth_mobility": mob.astype(float).tolist(),
                "hjorth_complexity": complexity.astype(float).tolist(),
            }
        }
