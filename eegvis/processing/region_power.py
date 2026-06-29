"""Per-lobe band power.

Mean band power within each lobe (frontal / central / temporal / parietal /
occipital), per band, for a region x band heatmap. Companion to the asymmetry
processor: same regional grouping, but absolute power per lobe rather than
left/right balance.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata
from .base import EEGProcessor
from .regions import LOBES, lobe_indices

BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}


class RegionPowerProcessor(EEGProcessor):
    name = "region_power"
    output_keys = ("region_power",)

    def __init__(self, enabled: bool = True, **options: Any):
        super().__init__(enabled, **options)
        self.window_seconds = float(self.opt("window_seconds", 2.0))
        self._sample_rate = 0.0
        self._groups: dict[str, list[int]] = {}
        self._regions: list[str] = []

    def configure(self, metadata: StreamMetadata) -> None:
        self._sample_rate = metadata.nominal_srate
        names = [metadata.channel_names[i] for i in metadata.eeg_channel_indices()]
        self._groups = lobe_indices(names)
        self._regions = [lb for lb in LOBES if self._groups[lb]]

    def process(self, state: ProcessingState) -> dict[str, Any]:
        sr = state.sample_rate or self._sample_rate
        eeg = self.latest(state, self.window_seconds)  # (n, n_eeg)
        n = eeg.shape[0]
        n_ch = eeg.shape[1]
        if sr <= 0 or n < 16 or n_ch == 0:
            return {}

        spectrum = np.fft.rfft(eeg * np.hanning(n)[:, None], axis=0)
        psd = (np.abs(spectrum) ** 2) / n  # (bins, n_eeg)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)

        bands: dict[str, list[float]] = {}
        for name, (lo, hi) in BANDS.items():
            mask = (freqs >= lo) & (freqs < hi)
            p = psd[mask, :].mean(axis=0) if mask.any() else np.zeros(n_ch)
            bands[name] = [
                float(p[self._groups[lb]].mean()) if self._groups[lb] else 0.0
                for lb in self._regions
            ]

        return {"region_power": {"regions": list(self._regions), "bands": bands}}
