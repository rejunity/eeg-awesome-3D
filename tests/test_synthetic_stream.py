import numpy as np

from eegvis.config import SyntheticConfig
from eegvis.lsl.synthetic import SyntheticStream


def test_synthetic_emits_expected_sample_count():
    cfg = SyntheticConfig(channel_count=37, sample_rate=250.0, noise=0.0, blink_artifacts=False)
    stream = SyntheticStream(cfg, start_time=0.0)
    chunk = stream.pull_chunk(now=1.0)  # 1 second
    assert chunk.data.shape == (250, 37)
    assert chunk.timestamps.shape == (250,)
    # Second pull continues where the first left off.
    chunk2 = stream.pull_chunk(now=1.5)
    assert chunk2.data.shape[0] == 125


def test_synthetic_metadata_matches_cgx_montage():
    cfg = SyntheticConfig(channel_count=37)
    stream = SyntheticStream(cfg)
    md = stream.metadata
    assert md.channel_count == 37
    assert "AF7" in md.channel_names
    # 29 EEG channels in Quick32r.
    assert sum(1 for t in md.channel_types if t == "eeg") == 29


def test_synthetic_no_samples_when_no_time_elapsed():
    cfg = SyntheticConfig(channel_count=8, sample_rate=100.0)
    stream = SyntheticStream(cfg, start_time=0.0)
    chunk = stream.pull_chunk(now=0.0)
    assert chunk.data.shape[0] == 0
