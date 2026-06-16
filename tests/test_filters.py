"""Tests for the global filter chain — currently the notch filter.

A notch (band-stop) filter must reject a narrow band around its centre frequency
(mains hum, 50 Hz in Europe / 60 Hz in the US) while leaving every other
frequency essentially untouched. We drive the pipeline's built-in notch with a
multi-channel signal where each channel is a pure sine at a different frequency,
then compare each channel's amplitude (RMS) before vs. after the filter.

Expected behaviour (notch at 50 Hz, sample rate 250 Hz, Q = 30):
  * 50 Hz channel (the notch centre): almost completely removed (RMS ratio ~0).
  * 10 Hz and 60 Hz channels (well outside the ~1.7 Hz notch width): pass through
    with ~unchanged amplitude (RMS ratio ~1).
  * With the notch disabled, the 50 Hz channel is untouched (ratio == 1) — i.e.
    the attenuation above is caused by the notch and nothing else.
"""

import numpy as np

from eegvis.config import ProcessingConfig
from eegvis.models import EEGChunk
from eegvis.processing.pipeline import Pipeline

from conftest import make_metadata


def _pipeline(md):
    pipe = Pipeline(
        ProcessingConfig(output_hz=30, rolling_window_seconds=4.0, processors=[])
    )
    pipe.configure(md)
    return pipe


def _feed_per_channel(pipe, freqs, md, seconds=3.0, chunk=0.04, settle=1.0):
    """Feed one pure sine per channel; return (raw, filtered) sample arrays.

    The first ``settle`` seconds (filter start-up transient + window fill) are
    skipped so the comparison is over the steady-state response.
    """
    sr = md.nominal_srate
    n = int(chunk * sr)
    total = int(seconds * sr)
    skip = int(settle * sr)
    raw: list = []
    filt: list = []
    start = 0
    while start < total:
        idx = np.arange(start, start + n)
        t = idx / sr
        data = np.zeros((n, md.channel_count), dtype=np.float32)
        for c, f in enumerate(freqs):
            data[:, c] = np.sin(2 * np.pi * f * t)
        frame = pipe.process(EEGChunk(data, t, md))
        if start >= skip:
            raw.extend(frame.samples)
            filt.extend(frame.filtered_samples)
        start += n
    return np.asarray(raw), np.asarray(filt)


def _rms(a):
    return np.sqrt(np.mean(a**2, axis=0))


def test_notch_rejects_centre_frequency_and_passes_others():
    md = make_metadata(n_eeg=3, sample_rate=250.0)
    pipe = _pipeline(md)
    pipe.set_notch(enabled=True, hz=50.0)

    # Channels: 0 = 50 Hz (the notch centre), 1 = 10 Hz, 2 = 60 Hz.
    raw, filt = _feed_per_channel(pipe, [50.0, 10.0, 60.0], md)
    ratio = _rms(filt) / _rms(raw)

    assert ratio[0] < 0.05  # 50 Hz removed (>95% attenuation; measured ~0.1%)
    assert ratio[1] > 0.95  # 10 Hz passes through untouched
    assert ratio[2] > 0.90  # 60 Hz (outside the notch) passes through


def test_notch_disabled_passes_centre_frequency():
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    pipe = _pipeline(md)  # notch off by default

    raw, filt = _feed_per_channel(pipe, [50.0], md)
    ratio = _rms(filt) / _rms(raw)

    # With no filter enabled the 50 Hz signal is unchanged (filtered == raw).
    assert ratio[0] > 0.95


def test_notch_follows_centre_frequency_when_retuned():
    md = make_metadata(n_eeg=2, sample_rate=250.0)
    pipe = _pipeline(md)
    pipe.set_notch(enabled=True, hz=60.0)  # US mains

    # Now the 60 Hz channel should be removed and the 50 Hz channel preserved.
    raw, filt = _feed_per_channel(pipe, [50.0, 60.0], md)
    ratio = _rms(filt) / _rms(raw)

    assert ratio[1] < 0.05  # 60 Hz removed
    assert ratio[0] > 0.95  # 50 Hz passes


# -- bandpass: out-of-band power is strongly attenuated, for every band -------

# Standard band edges (Hz) plus a custom range, and one tone in each band so
# there is always out-of-band signal to attenuate.
_BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
    "custom": (15.0, 25.0),
}
_TONES = [2.5, 6.0, 10.0, 20.0, 38.0]
_OUT_OF_BAND_MAX = 0.06  # out-of-band power must be < 6% of in-band power


def _filtered_signal(low, high, seconds=5.0, chunk=0.04, settle=2.0):
    """Collect the filtered (post-bandpass) channel-0 signal for a multi-tone input."""
    md = make_metadata(n_eeg=1, sample_rate=250.0)
    pipe = Pipeline(
        ProcessingConfig(output_hz=30, rolling_window_seconds=6.0, processors=[])
    )
    pipe.configure(md)
    pipe.set_bandpass(enabled=True, low_hz=low, high_hz=high)
    sr = md.nominal_srate
    n = 10
    skip = int(settle * sr)
    out = []
    si = 0
    while si < int(seconds * sr):
        t = np.arange(si, si + n) / sr
        sig = sum(np.sin(2 * np.pi * f * t) for f in _TONES).astype(np.float32)
        frame = pipe.process(EEGChunk(sig[:, None], t, md))
        if si >= skip:
            out.extend(r[0] for r in frame.filtered_samples)
        si += n
    return np.asarray(out), sr


def _out_in_power_ratio(x, sr, low, high):
    spectrum = np.fft.rfft(x * np.hanning(len(x)))
    psd = np.abs(spectrum) ** 2
    freqs = np.fft.rfftfreq(len(x), d=1.0 / sr)
    in_band = (freqs >= low) & (freqs < high)
    out_band = (freqs >= 0.5) & ~in_band  # ignore DC
    return float(psd[out_band].sum() / max(psd[in_band].sum(), 1e-20))


def test_bandpass_attenuates_out_of_band_for_all_bands():
    for name, (low, high) in _BANDS.items():
        x, sr = _filtered_signal(low, high)
        ratio = _out_in_power_ratio(x, sr, low, high)
        assert ratio < _OUT_OF_BAND_MAX, f"{name} {low}-{high}Hz out/in={ratio:.4f}"
