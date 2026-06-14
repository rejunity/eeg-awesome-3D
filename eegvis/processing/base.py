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
        # How often this processor recomputes:
        #   "realtime"  -> every tick that has new samples
        #   "frequency" -> at most run_hz times per second
        # The pipeline reuses the last output on ticks where it doesn't run.
        self.run_mode: str = options.get("run_mode", "realtime")
        self.run_hz: float = float(options.get("run_hz", 30.0))
        self._last_run_t: float = -1e9
        self._cached: dict[str, Any] = {}

    def configure(self, metadata: StreamMetadata) -> None:
        """Called once the stream metadata is known (channel count, srate)."""

    def reset(self) -> None:
        """Drop any internal/filter state (e.g. on reconnect)."""
        self._cached = {}
        self._last_run_t = -1e9

    def set_run(self, mode: str | None = None, hz: float | None = None) -> None:
        """Set the recompute cadence at runtime."""
        if mode in ("realtime", "frequency", "per-sample"):
            self.run_mode = mode
        if hz:
            self.run_hz = float(hz)

    def run(self, state: ProcessingState, now: float, has_new_data: bool) -> dict[str, Any]:
        """Run :meth:`process` if due (per run_mode), else reuse the last output."""
        if self.run_mode == "frequency":
            due = (now - self._last_run_t) >= (1.0 / max(self.run_hz, 0.01))
        else:  # realtime / per-sample -> run whenever new samples arrived
            due = has_new_data
        if due:
            self._last_run_t = now
            out = self.process(state)
            if out:  # keep the last good output for throttled/empty ticks
                self._cached = out
        return self._cached

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
