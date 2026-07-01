"""Tests for stream channel-name remapping to 10-20/10-10 labels."""

from __future__ import annotations

import json

import pytest

from eegvis.channel_map import (
    apply_channel_map,
    load_channel_map,
    resolve_channel_map,
)
from eegvis.config import load_config
from eegvis.models import StreamMetadata


def _meta(names, types=None):
    return StreamMetadata(
        name="s",
        type="EEG",
        source_id="sid",
        channel_count=len(names),
        nominal_srate=250.0,
        channel_names=list(names),
        channel_types=list(types) if types else None,
    )


def test_apply_remaps_names_case_insensitively():
    md = _meta(["eeg1", "EEG2", "misc"])
    apply_channel_map(md, {"EEG1": "Fp1", "eeg2": "Fp2"})
    assert md.channel_names == ["Fp1", "Fp2", "misc"]


def test_apply_marks_known_electrode_as_eeg():
    md = _meta(["X1", "X2"], types=["misc", "misc"])
    apply_channel_map(md, {"X1": "Cz", "X2": "NotAnElectrode"})
    # Cz is a known electrode -> promoted to eeg; the unknown target stays misc.
    assert md.channel_names == ["Cz", "NotAnElectrode"]
    assert md.channel_types == ["eeg", "misc"]


def test_apply_empty_map_is_noop():
    md = _meta(["a", "b"])
    before = list(md.channel_names)
    apply_channel_map(md, {})
    apply_channel_map(md, None)
    assert md.channel_names == before


def test_load_yaml_json_csv(tmp_path):
    y = tmp_path / "m.yaml"
    y.write_text("EEG1: Fp1\nEEG2: Fp2\n", encoding="utf-8")
    assert load_channel_map(y) == {"EEG1": "Fp1", "EEG2": "Fp2"}

    j = tmp_path / "m.json"
    j.write_text(json.dumps({"A": "Cz"}), encoding="utf-8")
    assert load_channel_map(j) == {"A": "Cz"}

    c = tmp_path / "m.csv"
    c.write_text("raw,canonical\nEEG1,Fp1\n# comment\nEEG2, Fp2\n", encoding="utf-8")
    assert load_channel_map(c) == {"EEG1": "Fp1", "EEG2": "Fp2"}


def test_resolve_inline_overrides_file(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("EEG1: Fp1\nEEG2: Fp2\n", encoding="utf-8")
    merged = resolve_channel_map({"EEG2": "F7"}, f)
    assert merged == {"EEG1": "Fp1", "EEG2": "F7"}


def test_load_rejects_non_mapping(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_channel_map(bad)


def test_load_config_folds_file_into_inline_map(tmp_path):
    mapfile = tmp_path / "map.yaml"
    mapfile.write_text("EEG1: Fp1\nEEG2: Fp2\n", encoding="utf-8")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        f"stream:\n  channel_map_file: {mapfile}\n  channel_map:\n    EEG2: F7\n",
        encoding="utf-8",
    )
    config = load_config(cfg)
    # File provides EEG1; inline overrides EEG2. (The bundled default also
    # contributes ch* entries, so assert the folded keys rather than equality.)
    assert config.stream.channel_map["EEG1"] == "Fp1"
    assert config.stream.channel_map["EEG2"] == "F7"


def test_default_config_maps_ch0_to_ch40_uniquely():
    """The bundled default remaps a generic ch0..ch40 stream to unique 10-10 names."""
    from eegvis.assets.electrodes_cgx import ELECTRODES_BY_NAME

    cmap = load_config(None).stream.channel_map
    for i in range(41):
        assert f"ch{i}" in cmap, f"ch{i} missing from default channel_map"
    targets = [cmap[f"ch{i}"] for i in range(41)]
    assert len(set(targets)) == 41, "default ch0..ch40 targets must be unique"
    assert all(t in ELECTRODES_BY_NAME for t in targets), "targets must be real electrodes"
