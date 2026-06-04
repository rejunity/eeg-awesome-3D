"""Download and prepare public EEG recordings for testing.

Default source: PhysioNet EEG Motor Movement/Imagery Database (eegmmidb), an
open 64-channel 10-10 dataset (160 Hz, EDF+) whose electrode names cover the
full CGX Quick32r montage. CC0/ODC-licensed and freely downloadable.

    https://physionet.org/content/eegmmidb/1.0.0/

A downloaded EDF is parsed, mapped to the CGX channels, and saved as a compact
``.npz`` (data + channel names + sample rate) under the recordings directory,
ready to be replayed as an LSL source (see eegvis/lsl/player.py).
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np

from .edf import read_edf
from .mapping import PreparedRecording, map_recording

PHYSIONET_BASE = "https://physionet.org/files/eegmmidb/1.0.0"

# Default recordings directory (gitignored; created on demand).
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "recordings"


def eegmmidb_url(subject: int, run: int) -> str:
    return f"{PHYSIONET_BASE}/S{subject:03d}/S{subject:03d}R{run:02d}.edf"


def download_file(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "eegvis/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as out:
        out.write(resp.read())
    return dest


def save_prepared(prep: PreparedRecording, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        dest,
        data=prep.data,
        channel_names=np.array(prep.channel_names),
        channel_types=np.array(prep.channel_types),
        sample_rate=np.float64(prep.sample_rate),
    )
    return dest


def load_prepared(path: Path) -> PreparedRecording:
    with np.load(path, allow_pickle=False) as npz:
        return PreparedRecording(
            channel_names=[str(x) for x in npz["channel_names"]],
            channel_types=[str(x) for x in npz["channel_types"]],
            sample_rate=float(npz["sample_rate"]),
            data=npz["data"],
            matched=[],
            missing=[],
        )


def fetch_eegmmidb(
    subject: int = 1,
    run: int = 3,
    out_dir: Path = DEFAULT_DIR,
) -> tuple[Path, PreparedRecording]:
    """Download one eegmmidb run, map it to CGX, and save a prepared .npz.

    Returns the saved ``.npz`` path and the prepared recording.
    """
    out_dir = Path(out_dir)
    edf_path = out_dir / f"S{subject:03d}R{run:02d}.edf"
    if not edf_path.exists():
        download_file(eegmmidb_url(subject, run), edf_path)

    recording = read_edf(edf_path)
    prep = map_recording(recording)
    npz_path = out_dir / f"S{subject:03d}R{run:02d}_cgx.npz"
    save_prepared(prep, npz_path)
    return npz_path, prep
