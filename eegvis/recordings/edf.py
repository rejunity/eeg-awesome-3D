"""Minimal dependency-free EDF / EDF+ reader.

Reads the European Data Format used by most public EEG datasets (e.g. PhysioNet)
without pulling in MNE/pyedflib. Handles the standard 256-byte header + per-signal
header block + interleaved data records, converts digital samples to physical
units, and drops the EDF+ "EDF Annotations" channel.

Reference: https://www.edfplus.info/specs/edf.html
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

ANNOTATION_LABEL = "EDF Annotations"


@dataclass
class EdfRecording:
    """A parsed EDF file.

    ``data`` has shape ``(n_samples, n_signals)`` in physical units, restricted
    to the signals sharing the most common sample rate (i.e. the EEG channels;
    the annotations channel and any off-rate signals are excluded).
    """

    labels: list[str]
    sample_rate: float
    data: np.ndarray  # (n_samples, n_signals)

    @property
    def n_samples(self) -> int:
        return self.data.shape[0]

    @property
    def duration_seconds(self) -> float:
        return self.n_samples / self.sample_rate if self.sample_rate else 0.0


def _ascii(raw: bytes) -> str:
    return raw.decode("ascii", errors="replace").strip()


def read_edf(path: str | Path) -> EdfRecording:
    """Parse an EDF/EDF+ file into an :class:`EdfRecording`."""
    path = Path(path)
    with path.open("rb") as f:
        header = f.read(256)
        if len(header) < 256:
            raise ValueError(f"{path} is too small to be an EDF file")

        n_records = int(_ascii(header[236:244]))
        record_duration = float(_ascii(header[244:252]))
        n_signals = int(_ascii(header[252:256]))

        # Per-signal header: each field is n_signals * fixed-width, concatenated.
        def field(width: int) -> list[bytes]:
            return [f.read(width) for _ in range(n_signals)]

        labels = [_ascii(b) for b in field(16)]
        _transducer = field(80)
        _phys_dim = field(8)
        phys_min = [float(_ascii(b)) for b in field(8)]
        phys_max = [float(_ascii(b)) for b in field(8)]
        dig_min = [float(_ascii(b)) for b in field(8)]
        dig_max = [float(_ascii(b)) for b in field(8)]
        _prefilter = field(80)
        samples_per_record = [int(_ascii(b)) for b in field(8)]
        _reserved = field(32)

        # Read the data section: n_records records, each is, per signal,
        # samples_per_record[s] int16 little-endian samples, interleaved by record.
        record_len = sum(samples_per_record)
        raw = np.frombuffer(
            f.read(n_records * record_len * 2), dtype="<i2"
        )

    if raw.size < n_records * record_len:
        # Truncated file: trim to whole records we actually have.
        n_records = raw.size // record_len
        raw = raw[: n_records * record_len]

    raw = raw.reshape(n_records, record_len)

    # Per-signal physical-unit scaling.
    offsets = np.cumsum([0] + samples_per_record)
    rates = [spr / record_duration for spr in samples_per_record]
    common_rate = max(set(rates), key=rates.count)

    chan_labels: list[str] = []
    columns: list[np.ndarray] = []
    for s in range(n_signals):
        if labels[s] == ANNOTATION_LABEL:
            continue
        if rates[s] != common_rate:
            continue  # off-rate auxiliary signal
        spr = samples_per_record[s]
        block = raw[:, offsets[s] : offsets[s] + spr]  # (n_records, spr)
        digital = block.reshape(-1).astype(np.float64)
        span = (dig_max[s] - dig_min[s]) or 1.0
        scale = (phys_max[s] - phys_min[s]) / span
        physical = (digital - dig_min[s]) * scale + phys_min[s]
        chan_labels.append(labels[s])
        columns.append(physical)

    if not columns:
        raise ValueError(f"{path} contained no usable signal channels")

    data = np.stack(columns, axis=1)  # (n_samples, n_signals)
    return EdfRecording(labels=chan_labels, sample_rate=float(common_rate), data=data)
