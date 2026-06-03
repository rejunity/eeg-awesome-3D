"""Processor registry.

Maps config ``name`` -> processor class. Adding a new processor means writing a
class (subclass of :class:`~eegvis.processing.base.EEGProcessor`) and adding one
line here; the receiver and WebSocket code never change.
"""

from __future__ import annotations

from .band_power import BandPowerProcessor
from .base import EEGProcessor
from .fft import FFTProcessor
from .filters import BandpassProcessor, NotchProcessor
from .normalization import NormalizationProcessor
from .short_fourier import ShortFourierVisualProcessor
from .smoothing import SmoothingProcessor

PROCESSORS: dict[str, type[EEGProcessor]] = {
    "bandpass": BandpassProcessor,
    "notch": NotchProcessor,
    "normalization": NormalizationProcessor,
    "fft": FFTProcessor,
    "band_power": BandPowerProcessor,
    "smoothing": SmoothingProcessor,
    "short_fourier": ShortFourierVisualProcessor,
}


def create_processor(name: str, enabled: bool, options: dict) -> EEGProcessor:
    if name not in PROCESSORS:
        raise KeyError(
            f"Unknown processor '{name}'. Known: {sorted(PROCESSORS)}"
        )
    return PROCESSORS[name](enabled=enabled, **options)
