"""Typed data models shared across the backend.

Two layers:

* Plain ``@dataclass`` containers (``StreamMetadata``, ``EEGChunk``,
  ``ProcessingState``) used inside the hot LSL/processing loops where NumPy
  arrays live and Pydantic validation would only get in the way.
* Pydantic models (``StatusPayload``, ``EEGFramePayload``) used at the
  WebSocket boundary so payloads serialize cleanly and match the documented
  contract in PLAN.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, Field

# Bump when the WebSocket payload contract changes in a breaking way.
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Internal dataclasses (NumPy-friendly, not serialized directly)
# ---------------------------------------------------------------------------


@dataclass
class StreamMetadata:
    """Description of an LSL (or synthetic) stream."""

    name: str
    type: str
    source_id: str | None
    channel_count: int
    nominal_srate: float
    channel_names: list[str]
    channel_types: list[str] | None = None

    def eeg_channel_indices(self) -> list[int]:
        """Indices of channels that are EEG (all of them if types unknown)."""
        if self.channel_types is None:
            return list(range(self.channel_count))
        return [i for i, t in enumerate(self.channel_types) if t == "eeg"]


@dataclass
class EEGChunk:
    """A block of samples pulled from the stream.

    ``data`` has shape ``(samples, channels)`` to match pylsl's chunk layout.
    """

    data: np.ndarray  # shape: samples x channels
    timestamps: np.ndarray  # shape: samples
    metadata: StreamMetadata


@dataclass
class ProcessingState:
    """Rolling state shared with processors for one stream.

    ``rolling_data`` has shape ``(window_samples, channels)``; the most recent
    sample is the last row.
    """

    sample_rate: float
    channel_names: list[str]
    rolling_data: np.ndarray  # the RAW window (never mutated by filters)
    rolling_timestamps: np.ndarray
    # The FILTERED window: raw run through the global filter chain (notch ->
    # bandpass -> …), kept in lockstep with rolling_data. Feature extractors read
    # this by default; the raw trace/electrodes and the view-band read raw.
    filtered_data: np.ndarray | None = None
    frame_index: int = 0
    # Number of real samples written into the rolling window so far (capped at
    # the window size); the leading zero pre-fill is excluded from `latest()`.
    valid_samples: int = 0
    # Samples appended in the most recent tick (for streaming processors that
    # must process each new sample exactly once, e.g. stateful filters).
    last_appended: int = 0
    # Samples appended since the processors last ran (>= last_appended when the
    # global run cadence throttles below the tick rate). A streaming processor
    # emits this many of its most-recent values per run.
    samples_since_run: int = 0
    # Indices (into channel_names) that are EEG channels and should drive visuals.
    eeg_channel_indices: list[int] = field(default_factory=list)

    @property
    def eeg_channel_names(self) -> list[str]:
        return [self.channel_names[i] for i in self.eeg_channel_indices]


# ---------------------------------------------------------------------------
# Pydantic payloads (WebSocket / HTTP boundary)
# ---------------------------------------------------------------------------


class StreamInfoPayload(BaseModel):
    name: str
    type: str
    source_id: str | None = None
    channel_count: int
    sample_rate: float
    channel_names: list[str]
    channel_types: list[str] | None = None


class StatusPayload(BaseModel):
    type: str = "status"
    schema_version: int = SCHEMA_VERSION
    connected: bool
    mode: str  # "lsl" | "synthetic" | "disconnected"
    message: str | None = None
    stream: StreamInfoPayload | None = None


class QualityPayload(BaseModel):
    samples_received: int = 0
    dropped_chunks: int = 0
    latency_ms: float = 0.0


class FFTPayload(BaseModel):
    freqs: list[float]
    # values[channel][bin]; downsampled / channel-limited as needed.
    values: list[list[float]]


class EEGFramePayload(BaseModel):
    type: str = "eeg_frame"
    schema_version: int = SCHEMA_VERSION
    frame_index: int
    timestamp: float
    sample_rate: float
    channels: list[str]
    # Raw last sample per EEG channel, before any processor (band) is applied.
    raw: list[float] = Field(default_factory=list)
    # All raw EEG samples in this chunk: samples[i] = per-channel values for the
    # i-th sample. Lets the browser draw the full source resolution on the trace
    # even though frames arrive in bursts.
    samples: list[list[float]] = Field(default_factory=list)
    # All EEG samples in this chunk AFTER the global filter chain (notch ->
    # bandpass): filtered_samples[i] = per-channel filtered value for sample i.
    # Drives the processed trace and (in "signal" mode) the electrodes. Equals
    # `samples` when no filter is enabled.
    filtered_samples: list[list[float]] = Field(default_factory=list)
    # Post-processor value per channel (raw last sample unless a processor sets it).
    latest: list[float]
    normalized: list[float]
    bands: dict[str, list[float]] = Field(default_factory=dict)
    # Generic per-channel scalar features keyed by name (Hjorth parameters, line
    # length, spectral entropy, 1/f slope, band-power ratios, band envelopes, …).
    # features[name][channel] -> value. Extensible without changing the contract.
    features: dict[str, list[float]] = Field(default_factory=dict)
    fft: FFTPayload | None = None
    # Short-Fourier visual parity output: per-channel energy for the 3 oscillators.
    short_fourier: dict[str, list[float]] | None = None
    quality: QualityPayload = Field(default_factory=QualityPayload)
