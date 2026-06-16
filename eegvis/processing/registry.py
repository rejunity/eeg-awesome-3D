"""Processor registry.

Maps config ``name`` -> processor class. Adding a new processor means writing a
class (subclass of :class:`~eegvis.processing.base.EEGProcessor`) and adding one
line here; the receiver and WebSocket code never change.
"""

from __future__ import annotations

from .aperiodic import AperiodicProcessor
from .asymmetry import AsymmetryProcessor
from .band_envelope import BandEnvelopeProcessor
from .band_power import BandPowerProcessor
from .base import EEGProcessor
from .fft import FFTProcessor
from .filters import BandpassProcessor, CARProcessor, NotchProcessor
from .hjorth import HjorthProcessor
from .line_length import LineLengthProcessor
from .normalization import NormalizationProcessor
from .short_fourier import ShortFourierVisualProcessor
from .smoothing import SmoothingProcessor
from .spectral_entropy import SpectralEntropyProcessor

PROCESSORS: dict[str, type[EEGProcessor]] = {
    # Preprocessing filters (transform the buffer in place; place these first).
    "bandpass": BandpassProcessor,
    "notch": NotchProcessor,
    "car": CARProcessor,
    # Display normalisation / smoothing.
    "normalization": NormalizationProcessor,
    "smoothing": SmoothingProcessor,
    # Feature extractors (pure functions of the window).
    "fft": FFTProcessor,
    "band_power": BandPowerProcessor,
    "band_envelope": BandEnvelopeProcessor,
    "hjorth": HjorthProcessor,
    "line_length": LineLengthProcessor,
    "spectral_entropy": SpectralEntropyProcessor,
    "aperiodic": AperiodicProcessor,
    "asymmetry": AsymmetryProcessor,
    "short_fourier": ShortFourierVisualProcessor,
}


def create_processor(name: str, enabled: bool, options: dict) -> EEGProcessor:
    if name not in PROCESSORS:
        raise KeyError(
            f"Unknown processor '{name}'. Known: {sorted(PROCESSORS)}"
        )
    return PROCESSORS[name](enabled=enabled, **options)
