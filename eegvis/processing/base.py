"""Base processor interface.

A processor is a small, independent, testable unit that reads a sliding window
of recent EEG samples (held in :class:`~eegvis.models.ProcessingState`) and
returns a dict of serializable output keys merged into the outgoing EEG frame.

Processors do NOT work on the incoming chunk directly — the pipeline appends
each chunk to the rolling window, and processors read whatever span of that
window they need via :meth:`latest` (e.g. a band-pass picks a longer span for
lower frequencies). The window is large (default 10 s, configurable).

Processors must not know about WebSockets or Three.js. They operate on NumPy
arrays and return plain lists/dicts. Keep scientific values separate from
display normalization.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import ProcessingState, StreamMetadata


class EEGProcessor:
    """Base class for processors. Subclasses override :meth:`process`.

    Subclasses set :attr:`name` and declare :attr:`output_keys` so the pipeline
    (and tests) know what they contribute to a frame.
    """

    name: str = "base"
    output_keys: tuple[str, ...] = ()

    def __init__(self, enabled: bool = True, **options: Any):
        self.enabled = enabled
        self.options = options

    def configure(self, metadata: StreamMetadata) -> None:
        """Called once the stream metadata is known (channel count, srate)."""

    def reset(self) -> None:
        """Drop any internal/filter state (e.g. on reconnect)."""

    def process(self, state: ProcessingState) -> dict[str, Any]:
        """Return a dict of output keys for this frame. Override in subclasses."""
        raise NotImplementedError

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _eeg_view(state: ProcessingState) -> np.ndarray:
        """Whole rolling window restricted to EEG channels: shape (window, n_eeg)."""
        if state.eeg_channel_indices:
            return state.rolling_data[:, state.eeg_channel_indices]
        return state.rolling_data

    def latest(self, state: ProcessingState, seconds: float | None = None) -> np.ndarray:
        """The most recent ``seconds`` of (valid) EEG samples, shape (n, n_eeg).

        Pass ``seconds=None`` for the whole filled window. Only real samples are
        returned (the zero pre-fill at start-up is excluded), and the request is
        clamped to what's actually available. A processor chooses ``seconds``
        based on its needs — e.g. a low-frequency band needs a longer span.
        """
        eeg = self._eeg_view(state)
        valid = min(state.valid_samples, eeg.shape[0])
        if valid <= 0:
            return eeg[:0]
        eeg = eeg[-valid:]
        if seconds is None:
            return eeg
        n = max(1, int(round(seconds * state.sample_rate)))
        n = min(n, eeg.shape[0])
        return eeg[-n:]

    def new_samples(self, state: ProcessingState) -> np.ndarray:
        """EEG samples appended in the most recent tick, shape (n_new, n_eeg).

        For streaming processors (e.g. stateful filters) that must consume each
        new sample exactly once rather than re-reading the whole window.
        """
        n = min(state.last_appended, state.valid_samples)
        eeg = self._eeg_view(state)
        n = min(n, eeg.shape[0])
        return eeg[-n:] if n > 0 else eeg[:0]

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)
