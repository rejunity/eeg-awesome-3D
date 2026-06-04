"""Tests for recording channel mapping (no network / no LSL required)."""

import numpy as np

from eegvis.assets.electrodes_cgx import QUICK32R
from eegvis.recordings.edf import EdfRecording
from eegvis.recordings.mapping import map_recording


def _fake_recording(labels, n=100):
    data = np.tile(np.arange(len(labels), dtype=np.float32), (n, 1))
    return EdfRecording(labels=labels, sample_rate=160.0, data=data)


def test_mapping_reorders_to_cgx_and_normalizes_names():
    # PhysioNet-style names: trailing dots, varied case.
    src = ["Af7.", "Fpz.", "F7.", "Fz.", "T7."]
    rec = _fake_recording(src)
    prep = map_recording(rec)

    # Output is the full Quick32r EEG montage in order.
    assert prep.channel_names == QUICK32R.eeg_channel_names
    assert prep.sample_rate == 160.0
    # The five provided channels are matched; the rest are missing.
    assert set(prep.matched) == {"AF7", "Fpz", "F7", "Fz", "T7"}
    assert "Cz" in prep.missing


def test_matched_channels_carry_source_data_missing_zero_filled():
    src = ["AF7", "Fpz"]  # indices 0 and 1 in the fake recording
    rec = _fake_recording(src, n=10)
    prep = map_recording(rec)

    names = prep.channel_names
    af7 = prep.data[:, names.index("AF7")]
    fpz = prep.data[:, names.index("Fpz")]
    cz = prep.data[:, names.index("Cz")]  # not provided -> zeros

    assert np.allclose(af7, 0.0)  # source column 0 == 0
    assert np.allclose(fpz, 1.0)  # source column 1 == 1
    assert np.allclose(cz, 0.0)
    assert prep.data.shape[1] == len(QUICK32R.eeg_channel_names)
