"""Hemispheric asymmetry.

For each band it computes per-channel band power, then:

- a per-channel signed asymmetry vs the channel's homologous (mirror) electrode,
  ``(P - P_mirror) / (P + P_mirror)`` in [-1, 1] — emitted as ``features``
  (``asym_<band>``) so it can tint the electrodes (diverging left/right) and show
  in the features pane. Midline / unpaired channels are 0.
- a per-lobe regional asymmetry ``(mean P_right - mean P_left) / (sum)`` — emitted
  as the ``asymmetry`` block (region x band), for the asymmetry pane. The
  frontal/alpha cell is the classic Frontal Alpha Asymmetry.

Positive = right hemisphere has more band power. Asymmetry is reference-sensitive
— enabling the ``car`` filter (common average reference) is recommended.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor
from .regions import LOBES, lobe_groups, mirror_indices

BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}


class AsymmetryProcessor(EEGProcessor):
    name = "asymmetry"
    output_keys = ("features", "asymmetry")

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.window_seconds = float(self.opt("window_seconds", 2.0))
        self._sample_rate = 0.0
        self._mirror: np.ndarray = np.zeros(0, dtype=int)
        self._groups: dict[str, dict[str, list[int]]] = {}
        self._regions: list[str] = []

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        # EEG channel names in the same order the window's EEG columns use.
        names = [metadata.channel_names[i] for i in metadata.eeg_channel_indices()]
        self._mirror = np.asarray(mirror_indices(names), dtype=int)
        self._groups = lobe_groups(names)
        # Only lobes with channels on both sides can have an asymmetry.
        self._regions = [
            lb for lb in LOBES if self._groups[lb]["L"] and self._groups[lb]["R"]
        ]

    def process(self, state: ProcessingState) -> dict[str, Any]:
        sr = state.sample_rate or self._sample_rate
        eeg = self.latest(state, self.window_seconds)  # (n, n_eeg)
        n = eeg.shape[0]
        n_ch = eeg.shape[1]
        if sr <= 0 or n < 16 or n_ch == 0 or self._mirror.shape[0] != n_ch:
            return {}

        spectrum = np.fft.rfft(eeg * np.hanning(n)[:, None], axis=0)
        psd = (np.abs(spectrum) ** 2) / n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)

        features: dict[str, list[float]] = {}
        region_bands: dict[str, list[float]] = {}
        for name, (lo, hi) in BANDS.items():
            mask = (freqs >= lo) & (freqs < hi)
            power = psd[mask, :].mean(axis=0) if mask.any() else np.zeros(n_ch)

            # Per-channel: signed asymmetry vs the homologous electrode.
            asym = np.zeros(n_ch)
            m = self._mirror
            paired = m >= 0
            pj = power[paired]
            pm = power[m[paired]]
            denom = pj + pm
            asym[paired] = np.divide(
                pj - pm, denom, out=np.zeros_like(denom), where=denom > 0
            )
            features[f"asym_{name}"] = asym.astype(float).tolist()

            # Per-lobe regional asymmetry (right vs left mean power).
            region_bands[name] = [
                self._region_asym(power, lb) for lb in self._regions
            ]

        return {
            "features": features,
            "asymmetry": {"regions": list(self._regions), "bands": region_bands},
        }

    def _region_asym(self, power: np.ndarray, lobe: str) -> float:
        left = power[self._groups[lobe]["L"]].mean()
        right = power[self._groups[lobe]["R"]].mean()
        total = left + right
        return float((right - left) / total) if total > 0 else 0.0
