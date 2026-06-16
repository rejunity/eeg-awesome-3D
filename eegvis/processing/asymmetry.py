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

Because ``(R-L)/(R+L)`` is scale-free, a band with almost no power (e.g. one cut
by the bandpass) would produce noisy, wildly swinging asymmetry. To avoid that,
every value is confidence-weighted by how much power the band actually carries
(its relative power vs. broadband): negligible-power bands are pulled to zero.
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

# Confidence ramp on a band's *relative* power (band / broadband). Below _REL_LO
# the band carries negligible power (e.g. it's outside the bandpass) so its
# asymmetry is noise and is fully suppressed; above _REL_HI it's trusted fully.
_REL_LO = 0.02
_REL_HI = 0.10


def _confidence(rel_power):
    """Map relative band power -> [0, 1] confidence (numpy-broadcasting)."""
    return np.clip((rel_power - _REL_LO) / (_REL_HI - _REL_LO), 0.0, 1.0)


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

        # Per-channel band power, and the per-channel broadband total used to
        # gauge how much power each band actually carries.
        power: dict[str, np.ndarray] = {}
        for name, (lo, hi) in BANDS.items():
            mask = (freqs >= lo) & (freqs < hi)
            power[name] = psd[mask, :].mean(axis=0) if mask.any() else np.zeros(n_ch)
        total = np.maximum(np.sum(list(power.values()), axis=0), 1e-20)  # (n_eeg,)

        # Per-lobe band power + lobe broadband total (for regional confidence).
        lobe_power = {
            lb: {nm: self._lobe_power(power[nm], lb) for nm in BANDS}
            for lb in self._regions
        }
        lobe_total = {
            lb: max(sum(lobe_power[lb].values()), 1e-20) for lb in self._regions
        }

        m = self._mirror
        paired = m >= 0
        features: dict[str, list[float]] = {}
        region_bands: dict[str, list[float]] = {}
        for name in BANDS:
            p = power[name]

            # Per-channel signed asymmetry vs the homologous electrode, then
            # CONFIDENCE-WEIGHTED by how much power this band carries on that
            # channel — so out-of-band / noise-floor bands don't sway at all.
            asym = np.zeros(n_ch)
            denom = p[paired] + p[m[paired]]
            asym[paired] = np.divide(
                p[paired] - p[m[paired]], denom,
                out=np.zeros_like(denom), where=denom > 0,
            )
            asym *= _confidence(p / total)
            features[f"asym_{name}"] = asym.astype(float).tolist()

            # Per-lobe regional asymmetry, weighted by the lobe's band confidence.
            vals = []
            for lb in self._regions:
                raw = self._region_asym(p, lb)
                conf = _confidence(lobe_power[lb][name] / lobe_total[lb])
                vals.append(raw * conf)
            region_bands[name] = vals

        return {
            "features": features,
            "asymmetry": {"regions": list(self._regions), "bands": region_bands},
        }

    def _lobe_power(self, power: np.ndarray, lobe: str) -> float:
        idx = self._groups[lobe]["L"] + self._groups[lobe]["R"]
        return float(power[idx].mean()) if idx else 0.0

    def _region_asym(self, power: np.ndarray, lobe: str) -> float:
        left = power[self._groups[lobe]["L"]].mean()
        right = power[self._groups[lobe]["R"]].mean()
        total = left + right
        return float((right - left) / total) if total > 0 else 0.0
