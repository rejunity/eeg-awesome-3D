"""Replay a prepared recording as an LSL stream.

Creates a ``pylsl.StreamOutlet`` advertising our CGX channel layout and pushes
the recording's samples in real time, so ``python -m eegvis run`` (or any LSL
consumer) can connect to it exactly like live hardware. ``pylsl`` is imported
lazily, so importing this module never requires liblsl.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..recordings.mapping import PreparedRecording
from .discovery import LSLNotAvailable, _import_pylsl


def load_recording(path: str | Path) -> PreparedRecording:
    """Load a prepared .npz, or parse+map a raw .edf on the fly."""
    path = Path(path)
    if path.suffix.lower() == ".npz":
        from ..recordings.download import load_prepared

        return load_prepared(path)
    if path.suffix.lower() == ".edf":
        from ..recordings.edf import read_edf
        from ..recordings.mapping import map_recording

        return map_recording(read_edf(path))
    raise ValueError(f"Unsupported recording type: {path.suffix} (use .edf or .npz)")


def _build_stream_info(prep: PreparedRecording, name: str):
    pylsl = _import_pylsl()
    info = pylsl.StreamInfo(
        name=name,
        type="EEG",
        channel_count=len(prep.channel_names),
        nominal_srate=prep.sample_rate,
        channel_format="float32",
        source_id=f"eegvis-replay-{name}",
    )
    # Advertise channel labels/types so the receiver reads them from desc().
    channels = info.desc().append_child("channels")
    for cname, ctype in zip(prep.channel_names, prep.channel_types):
        ch = channels.append_child("channel")
        ch.append_child_value("label", cname)
        ch.append_child_value("type", ctype.upper())
        ch.append_child_value("unit", "microvolts")
    return info


class RecordingPlayer:
    """Push a PreparedRecording to an LSL outlet at real-time pace."""

    def __init__(self, prep: PreparedRecording, name: str = "eegvis-replay", loop: bool = True):
        self.prep = prep
        self.name = name
        self.loop = loop

    def stream(self, chunk_seconds: float = 0.05) -> None:
        """Open the outlet and stream until interrupted (Ctrl-C)."""
        pylsl = _import_pylsl()
        info = _build_stream_info(self.prep, self.name)
        outlet = pylsl.StreamOutlet(info, chunk_size=0, max_buffered=360)

        data = self.prep.data.astype(np.float32)
        sr = self.prep.sample_rate
        chunk = max(1, int(chunk_seconds * sr))
        n = data.shape[0]
        period = chunk / sr

        while True:
            start_clock = time.monotonic()
            i = 0
            while i < n:
                block = data[i : i + chunk]
                outlet.push_chunk(block.tolist())
                i += chunk
                # Pace to wall clock.
                target = start_clock + (i / sr)
                sleep = target - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
            if not self.loop:
                break


def play_recording(
    path: str | Path,
    name: str = "eegvis-replay",
    loop: bool = True,
) -> None:
    """Convenience: load a recording and stream it (raises LSLNotAvailable)."""
    prep = load_recording(path)
    RecordingPlayer(prep, name=name, loop=loop).stream()


__all__ = ["RecordingPlayer", "play_recording", "load_recording", "LSLNotAvailable"]
