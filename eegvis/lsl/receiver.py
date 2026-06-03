"""LSL chunk receiver running on its own thread.

Pulls chunks from a ``pylsl.StreamInlet`` into a thread-safe queue, decoupled
from processing/broadcast. Annotates each chunk with a best-known CGX montage so
EEG vs aux channels are distinguished even when the stream omits channel types.

Reconnection: if the stream disappears, the receiver re-resolves and emits
status via the provided callbacks rather than crashing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from ..config import StreamConfig
from ..models import EEGChunk, StreamMetadata
from ..assets.electrodes_cgx import montage_for_channel_count
from .discovery import DiscoveredStream, choose_stream, discover_streams

StatusCallback = Callable[[str, bool, StreamMetadata | None], None]


def _annotate_metadata(metadata: StreamMetadata) -> StreamMetadata:
    """Fill channel names/types from a known CGX montage when the stream is bare."""
    montage = montage_for_channel_count(metadata.channel_count)
    if montage is None:
        if metadata.channel_types is None:
            metadata.channel_types = ["eeg"] * metadata.channel_count
        return metadata

    # If the stream didn't provide usable labels, adopt the montage's.
    bare = all(
        (not n) or n.startswith("ch") for n in metadata.channel_names
    )
    if bare:
        metadata.channel_names = list(montage.channel_names)
    if not metadata.channel_types or not any(
        t == "eeg" for t in metadata.channel_types
    ):
        metadata.channel_types = list(montage.channel_types)
    return metadata


class LSLReceiver:
    """Background LSL puller. Use :meth:`start` / :meth:`stop`; read via callback."""

    def __init__(
        self,
        config: StreamConfig,
        on_chunk: Callable[[EEGChunk], None],
        on_status: StatusCallback | None = None,
        max_chunk_duration: float = 0.2,
    ):
        self.config = config
        self._on_chunk = on_chunk
        self._on_status = on_status or (lambda *a: None)
        self._max_chunk_duration = max_chunk_duration
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.metadata: StreamMetadata | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lsl-receiver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # -- internals -----------------------------------------------------------

    def _resolve(self) -> DiscoveredStream | None:
        try:
            streams = discover_streams(timeout=self.config.resolve_timeout)
        except Exception:
            return None
        return choose_stream(streams, self.config)

    def _run(self) -> None:
        import pylsl

        while not self._stop.is_set():
            chosen = self._resolve()
            if chosen is None:
                self._on_status("searching", False, None)
                if self._stop.wait(1.0):
                    return
                continue

            metadata = _annotate_metadata(chosen.metadata)
            self.metadata = metadata
            inlet = pylsl.StreamInlet(chosen.info, max_chunklen=0, recover=False)
            self._on_status("connected", True, metadata)

            self._pull_loop(inlet, metadata)
            # Dropped out of pull loop -> stream lost; report and re-resolve.
            self._on_status("reconnecting", False, None)

    def _pull_loop(self, inlet, metadata: StreamMetadata) -> None:
        n_ch = metadata.channel_count
        empty_polls = 0
        while not self._stop.is_set():
            try:
                samples, timestamps = inlet.pull_chunk(
                    timeout=self._max_chunk_duration, max_samples=1024
                )
            except Exception:
                return  # stream lost
            if timestamps:
                data = np.asarray(samples, dtype=np.float32).reshape(-1, n_ch)
                ts = np.asarray(timestamps, dtype=np.float64)
                self._on_chunk(EEGChunk(data, ts, metadata))
                empty_polls = 0
            else:
                empty_polls += 1
                # Many consecutive empty polls => stream probably gone.
                if empty_polls > 50:
                    return
                time.sleep(0.005)
