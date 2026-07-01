"""Tests for LSL discovery logic that don't require pylsl/liblsl.

The stream-selection logic (choose_stream) is pure and testable with fake
DiscoveredStream objects; only the actual resolve needs pylsl.
"""

import pytest

from eegvis.config import StreamConfig
from eegvis.lsl.discovery import DiscoveredStream, choose_stream
from eegvis.models import StreamMetadata


def _stream(name, type_="EEG", n=37, source="s"):
    md = StreamMetadata(
        name=name, type=type_, source_id=source, channel_count=n,
        nominal_srate=250.0, channel_names=[f"ch{i}" for i in range(n)],
    )
    return DiscoveredStream(md, info=None)


def test_choose_prefers_cgx_when_unspecified():
    # Equal channel counts -> the CGX name preference breaks the tie.
    streams = [_stream("Generic EEG"), _stream("CGX Quick32r")]
    chosen = choose_stream(streams, StreamConfig(prefer_name_contains="cgx"))
    assert chosen.metadata.name == "CGX Quick32r"


def test_choose_picks_most_channels_by_default():
    streams = [_stream("Small", n=8), _stream("Big cap", n=64), _stream("Mid", n=32)]
    chosen = choose_stream(streams, StreamConfig())
    assert chosen.metadata.name == "Big cap"


def test_most_channels_beats_name_preference():
    # A bigger non-CGX cap wins over a smaller CGX stream (channels dominate).
    streams = [_stream("CGX Quick20r", n=19), _stream("Other EEG", n=64)]
    chosen = choose_stream(streams, StreamConfig(prefer_name_contains="cgx"))
    assert chosen.metadata.name == "Other EEG"


def test_name_preference_breaks_channel_count_ties():
    streams = [_stream("Other EEG", n=64), _stream("CGX cap", n=64)]
    chosen = choose_stream(streams, StreamConfig(prefer_name_contains="cgx"))
    assert chosen.metadata.name == "CGX cap"


def test_choose_filters_by_name():
    streams = [_stream("CGX"), _stream("Muse")]
    chosen = choose_stream(streams, StreamConfig(name="muse"))
    assert chosen.metadata.name == "Muse"


def test_choose_filters_by_type():
    streams = [_stream("Markers", type_="Markers"), _stream("Brain", type_="EEG")]
    chosen = choose_stream(streams, StreamConfig(type="EEG"))
    assert chosen.metadata.type == "EEG"


def test_choose_returns_none_when_no_match():
    streams = [_stream("CGX")]
    assert choose_stream(streams, StreamConfig(name="nope")) is None


def test_lsl_import_error_is_typed():
    """If pylsl is missing, discover_streams raises a clear typed error."""
    from eegvis.lsl.discovery import LSLNotAvailable, discover_streams

    try:
        import pylsl  # noqa: F401
    except Exception:
        with pytest.raises(LSLNotAvailable):
            discover_streams(timeout=0.1)
    else:
        pytest.skip("pylsl is installed; import path not exercised")
