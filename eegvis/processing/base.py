"""Base processor interface.

A processor is a small, independent, testable unit that reads the rolling
:class:`~eegvis.models.ProcessingState` (and the latest chunk) and returns a
dict of serializable output keys merged into the outgoing EEG frame.

Processors must not know about WebSockets or Three.js. They operate on NumPy
arrays and return plain lists/dicts. Keep scientific values separate from
display normalization.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..models import EEGChunk, ProcessingState, StreamMetadata


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

    def process(self, chunk: EEGChunk, state: ProcessingState) -> dict[str, Any]:
        """Return a dict of output keys for this frame. Override in subclasses."""
        raise NotImplementedError

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _eeg_view(state: ProcessingState) -> np.ndarray:
        """Rolling window restricted to EEG channels: shape (samples, n_eeg)."""
        if state.eeg_channel_indices:
            return state.rolling_data[:, state.eeg_channel_indices]
        return state.rolling_data

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)
