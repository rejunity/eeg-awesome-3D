"""Synthetic EEG generator.

Produces CGX-like multi-channel data without any hardware so the frontend and
processors can be developed and tested offline. Mirrors the spirit of the
random-fallback path in the Unity ``LSLInletReader.cs``, but generates real
oscillations at known frequencies so FFT/band-power tests have ground truth.
"""

from __future__ import annotations

import math

import numpy as np

from ..config import SyntheticConfig
from ..models import EEGChunk, StreamMetadata


def _channel_names(channel_count: int) -> tuple[list[str], list[str]]:
    """Pick CGX channel names/types matching the requested channel count."""
    from ..assets.electrodes_cgx import montage_for_channel_count

    montage = montage_for_channel_count(channel_count)
    if montage is not None:
        return list(montage.channel_names), list(montage.channel_types)
    names = [f"ch{i}" for i in range(channel_count)]
    types = ["eeg"] * channel_count
    return names, types


class SyntheticStream:
    """A pull-based synthetic stream with the same surface as the LSL receiver.

    Call :meth:`pull_chunk` repeatedly; it returns however many samples have
    "elapsed" since the previous call given ``now`` (a monotonic-ish seconds
    value supplied by the caller, so the generator stays deterministic in tests).
    """

    def __init__(self, config: SyntheticConfig, start_time: float = 0.0):
        self.config = config
        self.metadata = self._build_metadata()
        self._start_time = start_time
        self._last_time = start_time
        self._samples_emitted = 0
        # Stable per-channel phase offsets so channels are visually distinct.
        rng = np.random.default_rng(seed=1234)
        self._phase = rng.uniform(0, 2 * math.pi, size=self.config.channel_count)
        # Per-channel gain so the moving-min/max normalizer has something to chew on.
        self._gain = rng.uniform(0.6, 1.4, size=self.config.channel_count)
        self._rng = rng

    def _build_metadata(self) -> StreamMetadata:
        names, types = _channel_names(self.config.channel_count)
        return StreamMetadata(
            name="Synthetic EEG",
            type="EEG",
            source_id="synthetic-0",
            channel_count=self.config.channel_count,
            nominal_srate=self.config.sample_rate,
            channel_names=names,
            channel_types=types,
        )

    def reset(self, start_time: float = 0.0) -> None:
        self._start_time = start_time
        self._last_time = start_time
        self._samples_emitted = 0

    def pull_chunk(self, now: float) -> EEGChunk:
        """Return all samples generated between the last call and ``now``."""
        sr = self.config.sample_rate
        target_total = int(round((now - self._start_time) * sr))
        n = max(0, target_total - self._samples_emitted)
        if n == 0:
            empty = np.empty((0, self.config.channel_count), dtype=np.float32)
            return EEGChunk(empty, np.empty(0), self.metadata)

        # Absolute sample indices for this chunk -> timestamps.
        idx = np.arange(self._samples_emitted, self._samples_emitted + n)
        t = self._start_time + idx / sr  # shape (n,)
        data = self._generate(t)

        self._samples_emitted += n
        self._last_time = now
        return EEGChunk(data.astype(np.float32), t, self.metadata)

    def _generate(self, t: np.ndarray) -> np.ndarray:
        """Generate ``(len(t), channels)`` samples for absolute times ``t``."""
        cfg = self.config
        n = t.shape[0]
        ch = cfg.channel_count
        # (n, 1) time vs (1, ch) phase broadcasting.
        tt = t[:, None]
        phase = self._phase[None, :]

        signal = np.zeros((n, ch), dtype=np.float64)
        freqs = cfg.frequencies
        amps = cfg.amplitudes
        for k, f in enumerate(freqs):
            amp = amps[k] if k < len(amps) else amps[-1] if amps else 1.0
            signal += amp * np.sin(2 * math.pi * f * tt + phase)

        signal *= self._gain[None, :]

        if cfg.noise > 0:
            signal += self._rng.normal(0.0, cfg.noise, size=(n, ch))

        if cfg.blink_artifacts:
            signal += self._blink(t)[:, None] * self._frontal_mask()[None, :]

        # (Mains hum is injected source-agnostically by the engine, so it works
        # with real LSL streams too — not added here.)

        # Non-EEG channels (aux/acc/trigger): give them flatter, distinct signals.
        for i, ctype in enumerate(self.metadata.channel_types or []):
            if ctype != "eeg":
                signal[:, i] = self._aux_signal(t, i, ctype)

        return signal

    def _blink(self, t: np.ndarray) -> np.ndarray:
        """Roughly periodic eye-blink bumps (~once every 4 s)."""
        period = 4.0
        phase = (t % period) / period
        # Sharp Gaussian bump near the start of each period.
        return 6.0 * np.exp(-((phase - 0.05) ** 2) / (2 * 0.01**2))

    def _frontal_mask(self) -> np.ndarray:
        """Weight blink artifacts toward frontal channels (Fp*, AF*, F*)."""
        mask = np.zeros(self.config.channel_count, dtype=np.float64)
        for i, name in enumerate(self.metadata.channel_names):
            if name[:2] in ("Fp", "AF") or name[:1] == "F":
                mask[i] = 1.0
        return mask

    def _aux_signal(self, t: np.ndarray, i: int, ctype: str) -> np.ndarray:
        if ctype == "stim":
            return np.zeros_like(t)
        if "Packet" in self.metadata.channel_names[i]:
            return (self._samples_emitted + np.arange(t.shape[0])) % 65536
        # Slow accelerometer-ish drift.
        return 0.1 * np.sin(2 * math.pi * 0.2 * t + i)
