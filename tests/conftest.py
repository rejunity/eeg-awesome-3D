import math

import numpy as np
import pytest

from eegvis.models import EEGChunk, StreamMetadata


def make_metadata(n_eeg=8, sample_rate=250.0, with_aux=False):
    names = [f"E{i}" for i in range(n_eeg)]
    types = ["eeg"] * n_eeg
    if with_aux:
        names += ["trigger"]
        types += ["stim"]
    return StreamMetadata(
        name="test",
        type="EEG",
        source_id="t0",
        channel_count=len(names),
        nominal_srate=sample_rate,
        channel_names=names,
        channel_types=types,
    )


def make_sine_chunk(freq, metadata, n_samples, start_sample=0):
    """A chunk where every EEG channel is a sine at ``freq`` Hz."""
    sr = metadata.nominal_srate
    idx = np.arange(start_sample, start_sample + n_samples)
    t = idx / sr
    n_ch = metadata.channel_count
    data = np.zeros((n_samples, n_ch), dtype=np.float32)
    sine = np.sin(2 * math.pi * freq * t).astype(np.float32)
    for i, ctype in enumerate(metadata.channel_types):
        if ctype == "eeg":
            data[:, i] = sine
    return EEGChunk(data, t, metadata)


@pytest.fixture
def metadata():
    return make_metadata()
