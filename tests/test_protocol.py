from eegvis.config import load_config
from eegvis.models import EEGFramePayload, StatusPayload, StreamInfoPayload


def test_default_config_populates_feature_panes_without_altering_raw():
    # The default enables feature extractors (so the band/FFT/features panes have
    # data) but no signal-altering processor — the raw trace and electrode
    # colouring stay pass-through (they use raw `samples`/`latest`).
    cfg = load_config()
    assert cfg.server.port == 8765
    names = [p.name for p in cfg.processing.processors]
    assert "fft" in names and "band_power" in names
    altering = {"bandpass", "notch", "car", "normalization", "smoothing"}
    assert altering.isdisjoint(names)


def test_processor_options_preserved_when_configured():
    # Processor-specific options are still preserved via extra="allow" when a
    # processor is configured explicitly.
    from eegvis.config import ProcessorConfig

    bp = ProcessorConfig(name="bandpass", enabled=True, low_hz=1.0, high_hz=45.0)
    assert bp.options()["low_hz"] == 1.0
    assert bp.options()["high_hz"] == 45.0


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
