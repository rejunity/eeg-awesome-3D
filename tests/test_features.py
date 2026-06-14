import math

import numpy as np

from eegvis.config import ProcessingConfig, ProcessorConfig
from eegvis.models import EEGChunk
from eegvis.processing.pipeline import Pipeline

from conftest import make_metadata, make_sine_chunk


def _pipeline(*names, **common):
    cfg = ProcessingConfig(
        output_hz=30,
        rolling_window_seconds=6.0,
        processors=[ProcessorConfig(name=n, enabled=True, **common) for n in names],
    )
    return Pipeline(cfg)


def _feed(pipeline, freq, md, seconds=5.0, chunk=0.04):
    sr = md.nominal_srate
    n_per = int(chunk * sr)
    start = 0
    frame = None
    while start < int(seconds * sr):
        frame = pipeline.process(make_sine_chunk(freq, md, n_per, start))
        start += n_per
    return frame


# -- band power: relative power + ratios ------------------------------------

def test_band_power_relative_and_ratios():
    md = make_metadata(n_eeg=2, sample_rate=250.0)
    pipe = _pipeline("band_power")
    pipe.configure(md)
    f = _feed(pipe, 10.0, md)
    feats = f.features
    assert "rel_alpha" in feats and "theta_beta" in feats and "engagement" in feats
    # A 10 Hz signal: most relative power in alpha, and rel power sums to ~1.
    assert np.mean(feats["rel_alpha"]) > np.mean(feats["rel_beta"])
    total = sum(np.array(feats[f"rel_{b}"]) for b in ["delta", "theta", "alpha", "beta", "gamma"])
    assert np.allclose(total, 1.0, atol=1e-6)


# -- Hjorth: mobility tracks frequency --------------------------------------

def test_hjorth_mobility_increases_with_frequency():
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    pipe = _pipeline("hjorth")
    pipe.configure(md)
    mob10 = _feed(pipe, 10.0, md).features["hjorth_mobility"][0]
    pipe2 = _pipeline("hjorth")
    pipe2.configure(md)
    mob20 = _feed(pipe2, 20.0, md).features["hjorth_mobility"][0]
    assert mob20 > mob10 > 0


# -- line length: positive and larger for a busier signal -------------------

def test_line_length_positive():
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    pipe = _pipeline("line_length")
    pipe.configure(md)
    ll = _feed(pipe, 10.0, md).features["line_length"][0]
    assert ll > 0


# -- spectral entropy: low for a pure tone ----------------------------------

def test_spectral_entropy_low_for_pure_tone():
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    pipe = _pipeline("spectral_entropy")
    pipe.configure(md)
    ent = _feed(pipe, 10.0, md).features["spectral_entropy"][0]
    assert 0.0 <= ent < 0.5  # a single tone is far from a flat spectrum


# -- aperiodic slope: finite per-channel fit --------------------------------

def test_aperiodic_outputs_finite():
    md = make_metadata(n_eeg=2, sample_rate=250.0)
    pipe = _pipeline("aperiodic")
    pipe.configure(md)
    f = _feed(pipe, 10.0, md)
    slope = np.array(f.features["aperiodic_slope"])
    offset = np.array(f.features["aperiodic_offset"])
    assert slope.shape == (2,) and offset.shape == (2,)
    assert np.all(np.isfinite(slope)) and np.all(np.isfinite(offset))


# -- Hilbert band envelope: alpha envelope dominates for 10 Hz --------------

def test_band_envelope_alpha_dominates_for_10hz():
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    pipe = _pipeline("band_envelope")
    pipe.configure(md)
    feats = _feed(pipe, 10.0, md).features
    assert feats["env_alpha"][0] > feats["env_beta"][0]
    assert feats["env_alpha"][0] > feats["env_delta"][0]


# -- FFT: fixed 128-bin spectrum, peak near input frequency -----------------

def test_fft_is_128_bins_with_peak_at_input():
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    pipe = _pipeline("fft", update_hz=1000)
    pipe.configure(md)
    fft = _feed(pipe, 12.0, md).fft
    assert len(fft.freqs) == 128 and len(fft.values[0]) == 128
    freqs = np.array(fft.freqs)
    peak = freqs[int(np.argmax(fft.values[0]))]
    assert abs(peak - 12.0) <= 1.5


# -- CAR: removes the common signal across identical channels ---------------

def test_car_removes_common_signal():
    md = make_metadata(n_eeg=3, sample_rate=250.0)
    pipe = _pipeline("car", "hjorth")  # CAR first, then a feature on cleaned data
    pipe.configure(md)
    # make_sine_chunk fills every EEG channel with the same sine -> fully common.
    f = _feed(pipe, 10.0, md)
    activity = np.array(f.features["hjorth_activity"])
    assert np.all(activity < 1e-6)  # common signal subtracted away


# -- bandpass attenuates out-of-band power ----------------------------------

def test_bandpass_attenuates_out_of_band():
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    # Pass only alpha; feed a 40 Hz signal -> band_power alpha should stay low
    # relative to a no-filter reference.
    filtered = _pipeline_with_opts(
        [("bandpass", {"low_hz": 8.0, "high_hz": 13.0}), ("band_power", {})]
    )
    filtered.configure(md)
    a_filt = np.mean(_feed(filtered, 40.0, md).features["rel_gamma"])
    ref = _pipeline("band_power")
    ref.configure(md)
    a_ref = np.mean(_feed(ref, 40.0, md).features["rel_gamma"])
    # The 40 Hz (gamma) relative power is much lower once we band-pass to alpha.
    assert a_filt < a_ref


def _pipeline_with_opts(specs):
    cfg = ProcessingConfig(
        output_hz=30,
        rolling_window_seconds=6.0,
        processors=[ProcessorConfig(name=n, enabled=True, **o) for n, o in specs],
    )
    return Pipeline(cfg)
