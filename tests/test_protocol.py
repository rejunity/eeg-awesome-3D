from eegvis.config import load_config
from eegvis.models import EEGFramePayload, StatusPayload, StreamInfoPayload


def test_default_config_loads_and_has_processors():
    cfg = load_config()
    assert cfg.server.port == 8765
    names = [p.name for p in cfg.processing.processors]
    assert "normalization" in names
    assert "band_power" in names
    # processor-specific options are preserved via extra="allow"
    bp = next(p for p in cfg.processing.processors if p.name == "bandpass")
    assert bp.options()["low_hz"] == 1.0


def test_status_payload_serialization():
    payload = StatusPayload(
        connected=True,
        mode="synthetic",
        stream=StreamInfoPayload(
            name="Synthetic EEG", type="EEG", channel_count=37,
            sample_rate=250.0, channel_names=["AF7"],
        ),
    )
    d = payload.model_dump()
    assert d["type"] == "status"
    assert d["connected"] is True
    assert d["stream"]["channel_count"] == 37
    assert d["schema_version"] >= 1


def test_eeg_frame_payload_matches_contract():
    payload = EEGFramePayload(
        frame_index=1, timestamp=1.0, sample_rate=250.0,
        channels=["AF7", "Fpz"], latest=[0.1, -0.2], normalized=[0.5, -0.5],
        bands={"alpha": [0.6, 0.4]},
    )
    d = payload.model_dump()
    assert d["type"] == "eeg_frame"
    assert d["channels"] == ["AF7", "Fpz"]
    assert d["bands"]["alpha"] == [0.6, 0.4]
    assert d["fft"] is None
