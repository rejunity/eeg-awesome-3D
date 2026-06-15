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
