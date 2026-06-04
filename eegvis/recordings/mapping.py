"""Map an arbitrary EEG recording onto our CGX channel layout.

Public datasets use 10-10/10-20 names with varied casing and punctuation
(PhysioNet writes ``Fp1.``, ``Af7.``, ``Fpz.``). We normalize names and select
the channels matching the CGX Quick32r EEG montage, in montage order, so the
resulting stream maps cleanly onto the frontend electrodes. Missing channels
are zero-filled (and reported) so the channel count stays stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ..assets.electrodes_cgx import QUICK32R, CGXMontage
from .edf import EdfRecording


@dataclass
class PreparedRecording:
    channel_names: list[str]
    channel_types: list[str]
    sample_rate: float
    data: np.ndarray  # (n_samples, n_channels)
    matched: list[str]
    missing: list[str]


def _norm(name: str) -> str:
    """Normalize an electrode label for matching: strip punctuation, uppercase."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def map_recording(
    recording: EdfRecording, montage: CGXMontage = QUICK32R
) -> PreparedRecording:
    """Reorder/select a recording's channels to the CGX EEG montage order."""
    lookup: dict[str, int] = {}
    for i, label in enumerate(recording.labels):
        lookup.setdefault(_norm(label), i)

    eeg_names = montage.eeg_channel_names
    n_samples = recording.n_samples
    data = np.zeros((n_samples, len(eeg_names)), dtype=np.float32)

    matched: list[str] = []
    missing: list[str] = []
    for col, name in enumerate(eeg_names):
        idx = lookup.get(_norm(name))
        if idx is None:
            missing.append(name)
            continue
        data[:, col] = recording.data[:, idx]
        matched.append(name)

    return PreparedRecording(
        channel_names=list(eeg_names),
        channel_types=["eeg"] * len(eeg_names),
        sample_rate=recording.sample_rate,
        data=data,
        matched=matched,
        missing=missing,
    )
