import numpy as np

from eegvis.config import ProcessingConfig
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
