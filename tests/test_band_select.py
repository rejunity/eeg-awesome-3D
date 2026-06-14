import math

import numpy as np

from eegvis.config import ProcessingConfig
from eegvis.models import EEGChunk
from eegvis.processing.pipeline import Pipeline

from conftest import make_metadata, make_sine_chunk


def _feed(pipeline, freq, metadata, seconds=2.0, chunk=0.04):
    sr = metadata.nominal_srate
    n_per = int(chunk * sr)
    start = 0
    frame = None
    while start < int(seconds * sr):
        frame = pipeline.process(make_sine_chunk(freq, metadata, n_per, start))
        start += n_per
    return frame


def _pipeline():
    return Pipeline(ProcessingConfig(output_hz=30, rolling_window_seconds=2.0, processors=[]))


def test_passthrough_returns_raw_latest():
    md = make_metadata(n_eeg=3, sample_rate=250.0)
    pipe = _pipeline()
    pipe.configure(md)
    # band None (default) -> latest is the raw last sample (a 10 Hz sine value).
    frame = _feed(pipe, 10.0, md)
    assert len(frame.latest) == 3
    assert all(abs(v) <= 1.0001 for v in frame.latest)  # raw sine in [-1, 1]


def test_band_select_alpha_dominates_for_10hz():
    md = make_metadata(n_eeg=2, sample_rate=250.0)
    pipe = _pipeline()
    pipe.configure(md)

    pipe.set_band("alpha")
    alpha_amp = np.mean(_feed(pipe, 10.0, md).latest)
    pipe.set_band("beta")
    beta_amp = np.mean(_feed(pipe, 10.0, md).latest)

    # A 10 Hz signal has far more amplitude in the alpha band than in beta.
    assert alpha_amp > beta_amp


def _multi_sine_chunk(freqs, md, n_samples, start_sample):
    """A chunk whose EEG channels are a sum of sines (so the band-pass shapes it)."""
    sr = md.nominal_srate
    idx = np.arange(start_sample, start_sample + n_samples)
    t = idx / sr
    sig = sum(np.sin(2 * math.pi * f * t) for f in freqs).astype(np.float32)
    data = np.zeros((n_samples, md.channel_count), dtype=np.float32)
    for i, ctype in enumerate(md.channel_types):
        if ctype == "eeg":
            data[:, i] = sig
    return EEGChunk(data, t, md)


def _band_stream(run_mode, run_hz, md, seconds=8.0, chunk_dt=0.05, freqs=(6.0, 10.0, 22.0)):
    """Run band_select at a given filter rate, returning the channel-0 band stream.

    Drives ingest/emit on an explicit clock so "frequency" throttling is
    deterministic. The stream is indexed by absolute sample (every sample is
    emitted exactly once, in order — "frequency" just delivers them in batches).
    """
    pipe = Pipeline(
        ProcessingConfig(output_hz=30, rolling_window_seconds=6.0, processors=[])
    )
    pipe.configure(md)
    pipe.set_band("alpha")
    pipe.band_select.set_run(run_mode, run_hz)

    sr = md.nominal_srate
    n_per = int(chunk_dt * sr)
    total = int(seconds * sr)
    stream: list[float] = []
    start = tick = 0
    while start < total:
        pipe.ingest(_multi_sine_chunk(freqs, md, n_per, start))
        frame = pipe.emit(tick * chunk_dt)
        stream.extend(row[0] for row in frame.band_samples)
        start += n_per
        tick += 1
    return np.array(stream)


def test_band_stream_matches_across_filter_rates():
    """The filtered band signal must be identical whether the filter runs
    per-sample or batched at a lower frequency — only the delivery cadence
    differs, not the values."""
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    per_sample = _band_stream("per-sample", 0.0, md)
    frequency = _band_stream("frequency", 10.0, md)

    n = min(len(per_sample), len(frequency))
    assert n > 0
    # Compare the settled region (after the 6 s window has filled): both rates
    # filter the full window for these samples, so the values must match closely.
    sr = md.nominal_srate
    a, b = int(6.5 * sr), int(7.5 * sr)
    assert b <= n
    ps, fq = per_sample[a:b], frequency[a:b]
    assert ps.shape == fq.shape and ps.size > 0
    # Tight match relative to the signal amplitude.
    assert np.max(np.abs(ps - fq)) < 1e-6 * max(1.0, np.max(np.abs(ps)))
