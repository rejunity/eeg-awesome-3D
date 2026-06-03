import numpy as np

from eegvis.config import ProcessingConfig, ProcessorConfig
from eegvis.processing.pipeline import Pipeline
from eegvis.processing.band_power import BandPowerProcessor
from eegvis.processing.fft import FFTProcessor
from eegvis.processing.normalization import NormalizationProcessor

from conftest import make_metadata, make_sine_chunk


def _feed_window(pipeline, freq, metadata, seconds=2.0, chunk=0.04):
    """Feed several chunks of a pure sine so the rolling window fills up."""
    sr = metadata.nominal_srate
    n_per = int(chunk * sr)
    total = int(seconds * sr)
    start = 0
    frame = None
    while start < total:
        c = make_sine_chunk(freq, metadata, n_per, start_sample=start)
        frame = pipeline.process(c)
        start += n_per
    return frame


def _band_pipeline():
    cfg = ProcessingConfig(
        output_hz=30,
        rolling_window_seconds=2.0,
        processors=[
            ProcessorConfig(name="band_power", enabled=True),
            ProcessorConfig(name="fft", enabled=True, update_hz=30),
        ],
    )
    return Pipeline(cfg)


def test_alpha_dominant_for_10hz():
    metadata = make_metadata(n_eeg=4, sample_rate=250.0)
    pipeline = _band_pipeline()
    pipeline.configure(metadata)
    frame = _feed_window(pipeline, 10.0, metadata)
    bands = frame.bands
    # Alpha (8-13) should dominate for a 10 Hz signal.
    assert np.mean(bands["alpha"]) >= np.mean(bands["beta"])
    assert np.mean(bands["alpha"]) >= np.mean(bands["delta"])


def test_beta_dominant_for_20hz():
    metadata = make_metadata(n_eeg=4, sample_rate=250.0)
    pipeline = _band_pipeline()
    pipeline.configure(metadata)
    frame = _feed_window(pipeline, 20.0, metadata)
    bands = frame.bands
    assert np.mean(bands["beta"]) >= np.mean(bands["alpha"])


def test_fft_peak_matches_input_frequency():
    metadata = make_metadata(n_eeg=2, sample_rate=250.0)
    proc = FFTProcessor(window_seconds=1.0, update_hz=1000, max_freq_hz=60)
    cfg = ProcessingConfig(
        output_hz=30, rolling_window_seconds=2.0,
        processors=[ProcessorConfig(name="fft", enabled=True, update_hz=1000, max_freq_hz=60)],
    )
    pipeline = Pipeline(cfg)
    pipeline.configure(metadata)
    frame = _feed_window(pipeline, 12.0, metadata)
    fft = frame.fft
    freqs = np.array(fft.freqs)
    vals = np.array(fft.values[0])
    peak_freq = freqs[np.argmax(vals)]
    assert abs(peak_freq - 12.0) <= 1.5


def test_normalization_output_range():
    metadata = make_metadata(n_eeg=4, sample_rate=250.0)
    proc = NormalizationProcessor(method="moving_minmax", reactivity=0.9)
    proc.configure(metadata)
    cfg = ProcessingConfig(
        output_hz=30, rolling_window_seconds=2.0,
        processors=[ProcessorConfig(name="normalization", enabled=True)],
    )
    pipeline = Pipeline(cfg)
    pipeline.configure(metadata)
    frame = _feed_window(pipeline, 10.0, metadata)
    norm = np.array(frame.normalized)
    assert norm.shape[0] == 4
    assert np.all(norm >= -1.0001) and np.all(norm <= 1.0001)


def test_processors_can_be_disabled_and_reordered():
    metadata = make_metadata(n_eeg=4)
    cfg = ProcessingConfig(
        output_hz=30, rolling_window_seconds=1.0,
        processors=[
            ProcessorConfig(name="band_power", enabled=False),
            ProcessorConfig(name="normalization", enabled=True),
        ],
    )
    pipeline = Pipeline(cfg)
    pipeline.configure(metadata)
    frame = _feed_window(pipeline, 10.0, metadata, seconds=1.0)
    # band_power disabled -> no bands populated
    assert frame.bands == {}
    assert len(frame.normalized) == 4


def test_aux_channels_excluded_from_eeg_output():
    metadata = make_metadata(n_eeg=4, with_aux=True)
    cfg = ProcessingConfig(
        output_hz=30, rolling_window_seconds=1.0,
        processors=[ProcessorConfig(name="normalization", enabled=True)],
    )
    pipeline = Pipeline(cfg)
    pipeline.configure(metadata)
    frame = _feed_window(pipeline, 10.0, metadata, seconds=1.0)
    # Only the 4 EEG channels appear, not the trigger.
    assert frame.channels == ["E0", "E1", "E2", "E3"]
    assert len(frame.normalized) == 4
