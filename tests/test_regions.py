import math

import numpy as np

from eegvis.config import ProcessingConfig, ProcessorConfig
from eegvis.models import EEGChunk, StreamMetadata
from eegvis.processing.pipeline import Pipeline
from eegvis.processing.regions import (
    lobe_groups,
    mirror_indices,
    mirror_label,
    parse_label,
)


def test_parse_label():
    assert parse_label("F3") == ("frontal", "L")
    assert parse_label("F4") == ("frontal", "R")
    assert parse_label("Fp1") == ("frontal", "L")
    assert parse_label("FC5") == ("central", "L")
    assert parse_label("Cz") == ("central", "M")
    assert parse_label("T8") == ("temporal", "R")
    assert parse_label("P7") == ("parietal", "L")
    assert parse_label("PO8") == ("occipital", "R")
    assert parse_label("Oz") == ("occipital", "M")


def test_mirror_label_and_indices():
    assert mirror_label("F3") == "F4"
    assert mirror_label("F4") == "F3"
    assert mirror_label("O2") == "O1"
    assert mirror_label("Oz") is None
    assert mirror_indices(["F3", "F4", "Oz"]) == [1, 0, -1]


def test_lobe_groups():
    groups = lobe_groups(["F3", "F4", "O1", "O2", "Cz"])
    assert groups["frontal"] == {"L": [0], "R": [1]}
    assert groups["occipital"] == {"L": [2], "R": [3]}
    assert groups["central"] == {"L": [], "R": []}  # Cz is midline


def _md(names):
    return StreamMetadata(
        name="t", type="EEG", source_id="t0",
        channel_count=len(names), nominal_srate=250.0,
        channel_names=names, channel_types=["eeg"] * len(names),
    )


def test_asymmetry_detects_stronger_right_hemisphere():
    md = _md(["F3", "F4", "O1", "O2"])
    pipe = Pipeline(
        ProcessingConfig(
            output_hz=30, rolling_window_seconds=4.0,
            processors=[ProcessorConfig(name="asymmetry")],
        )
    )
    pipe.configure(md)

    sr = 250.0
    si = 0
    frame = None
    # 10 Hz alpha, right channels (F4, O2) 3x the amplitude of the left.
    amp = [0.5, 1.5, 0.5, 1.5]
    while si < int(5.0 * sr):
        n = 12
        t = np.arange(si, si + n) / sr
        wave = np.sin(2 * math.pi * 10 * t)
        data = np.column_stack([a * wave for a in amp]).astype(np.float32)
        frame = pipe.process(EEGChunk(data, t, md))
        si += n

    asym = np.array(frame.features["asym_alpha"])
    # F4 (right, idx 1) positive; F3 (left, idx 0) the negative mirror.
    assert asym[1] > 0.3
    assert asym[0] < -0.3
    assert abs(asym[0] + asym[1]) < 1e-6  # mirror pair is antisymmetric

    # Regional: frontal & occipital alpha asymmetry are right-positive.
    ap = frame.asymmetry
    assert set(ap.regions) == {"frontal", "occipital"}
    fi = ap.regions.index("frontal")
    assert ap.bands["alpha"][fi] > 0.3


def test_asymmetry_suppresses_low_power_bands():
    md = _md(["F3", "F4"])
    pipe = Pipeline(
        ProcessingConfig(
            output_hz=30, rolling_window_seconds=4.0,
            processors=[ProcessorConfig(name="asymmetry")],
        )
    )
    pipe.configure(md)

    sr = 250.0
    si = 0
    frame = None
    while si < int(5.0 * sr):
        n = 12
        t = np.arange(si, si + n) / sr
        alpha = np.sin(2 * math.pi * 10 * t)
        gamma = np.sin(2 * math.pi * 35 * t)
        # Alpha clearly right-dominant (present); a tiny gamma exists only on the
        # left (huge raw asymmetry, but negligible power -> should be suppressed).
        f3 = 0.7 * alpha + 0.1 * gamma
        f4 = 1.3 * alpha
        data = np.column_stack([f3, f4]).astype(np.float32)
        frame = pipe.process(EEGChunk(data, t, md))
        si += n

    ap = frame.asymmetry
    fi = ap.regions.index("frontal")
    assert ap.bands["alpha"][fi] > 0.2  # present band: real asymmetry shown
    assert abs(ap.bands["gamma"][fi]) < 0.1  # noise-floor band: suppressed


def test_asymmetry_measures_power_ratio():
    """The asymmetry equals the band-power ratio (R-L)/(R+L); power ~ amplitude^2."""
    md = _md(["F3", "F4"])
    pipe = Pipeline(
        ProcessingConfig(
            output_hz=30, rolling_window_seconds=4.0,
            processors=[ProcessorConfig(name="asymmetry")],
        )
    )
    pipe.configure(md)

    sr = 250.0
    si = 0
    frame = None
    aL, aR = 0.5, 1.0  # left/right alpha amplitudes -> powers 0.25 and 1.0
    while si < int(5.0 * sr):
        n = 12
        t = np.arange(si, si + n) / sr
        wave = np.sin(2 * math.pi * 10 * t)
        data = np.column_stack([aL * wave, aR * wave]).astype(np.float32)
        frame = pipe.process(EEGChunk(data, t, md))
        si += n

    expected = (aR**2 - aL**2) / (aR**2 + aL**2)  # = 0.6
    fi = frame.asymmetry.regions.index("frontal")
    assert abs(frame.asymmetry.bands["alpha"][fi] - expected) < 0.05

    asym = frame.features["asym_alpha"]
    assert abs(asym[1] - expected) < 0.05  # F4 (right)
    assert abs(asym[0] + expected) < 0.05  # F3 (left) = -expected


def test_confidence_by_band_power():
    """The confidence ramp: 0 below _REL_LO, 1 above _REL_HI, linear between."""
    from eegvis.processing.asymmetry import _REL_HI, _REL_LO, _confidence

    assert float(_confidence(0.0)) == 0.0
    assert float(_confidence(_REL_LO)) == 0.0
    assert float(_confidence(_REL_LO - 0.01)) == 0.0
    assert abs(float(_confidence(_REL_HI)) - 1.0) < 1e-9
    assert float(_confidence(0.5)) == 1.0
    mid = (_REL_LO + _REL_HI) / 2
    assert abs(float(_confidence(mid)) - 0.5) < 1e-9

    # Monotonic non-decreasing across the range.
    xs = np.linspace(0.0, 0.2, 50)
    c = _confidence(xs)
    assert np.all(np.diff(c) >= -1e-12)
    assert c[0] == 0.0 and c[-1] == 1.0
