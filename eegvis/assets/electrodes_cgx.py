"""CGX electrode metadata ported from the Unity reference.

Source of truth: ``EEGViewer-Unity/Assets/LSLInletReader.cs`` (electrode names and
3D positions) and the Python reference ``lsl_plot_blitting_cgx.py`` (channel maps
for the 27-channel Quick20r and 37-channel Quick32r CGX streams).

Coordinate conversion
---------------------
Unity stored positions in a head-centred frame where:

    Unity x = anterior(+) / posterior(-)
    Unity y = left(+)     / right(-)
    Unity z = superior(+) / inferior(-)

with a head "radius" of roughly 85 units. We convert to a Three.js-friendly,
right-handed, Y-up frame where the head faces +Z (toward the default camera):

    three.x =  right     = -unity.y
    three.y =  up        =  unity.z
    three.z =  anterior  =  unity.x

and divide by :data:`UNITY_HEAD_SCALE` so the scalp lands on a unit-ish sphere
(radius ~1.0). This single scale factor is the only magic number; keep it here.
"""

from __future__ import annotations

from dataclasses import dataclass

# The Unity electrode coordinates sit on a sphere of roughly this radius.
# Dividing by it yields a head of radius ~1.0 in the browser scene.
UNITY_HEAD_SCALE = 85.0


@dataclass(frozen=True)
class Electrode:
    """A single scalp electrode with a normalized 3D position."""

    name: str
    # Position in the browser frame (right-handed, Y up, +Z anterior), head radius ~1.
    x: float
    y: float
    z: float

    def as_list(self) -> list[float]:
        return [self.x, self.y, self.z]


# Electrode names and Unity positions, copied verbatim from LSLInletReader.cs.
# (name, unity_x, unity_y, unity_z)
_UNITY_ELECTRODES: list[tuple[str, float, float, float]] = [
    ("AF7", 68.7, 49.7, -5.96),
    ("Fpz", 85.0, 0.0, -1.79),
    ("F7", 49.9, 68.4, -7.49),
    ("Fz", 60.7, 0.0, 59.5),
    ("T7", 0.0, 84.5, -8.85),
    ("FC6", 28.8, -76.2, 24.2),
    ("Fp1", 80.8, 26.1, -4.0),
    ("F4", 57.6, -48.1, 39.9),
    ("C4", 0.0, -63.2, 56.9),
    ("Oz", -85.0, 0.0, -1.79),
    ("CP6", -28.8, -76.2, 24.2),
    ("Cz", 0.0, 0.0, 85.0),
    ("PO8", -68.7, -49.7, -5.95),
    ("CP5", -28.8, 76.2, 24.2),
    ("O2", -80.8, -26.1, -4.0),
    ("O1", -80.8, 26.1, -4.0),
    ("P3", -57.6, 48.2, 39.9),
    ("P4", -57.6, -48.1, 39.9),
    ("P7", -49.9, 68.4, -7.49),
    ("P8", -49.9, -68.4, -7.49),
    ("Pz", -60.7, 0.0, 59.5),
    ("PO7", -68.7, 49.7, -5.96),
    ("T8", 0.0, -84.5, -8.85),
    ("C3", 0.0, 63.2, 56.9),
    ("Fp2", 80.8, -26.1, -4.0),
    ("F3", 57.6, 48.2, 39.9),
    ("F8", 49.9, -68.4, -7.49),
    ("FC5", 28.8, 76.2, 24.2),
    ("AF8", 68.7, -49.7, -5.95),
    # A1 was present but commented out in the Unity reference.
]


def _to_browser_frame(ux: float, uy: float, uz: float) -> tuple[float, float, float]:
    """Convert a Unity head coordinate to the normalized browser frame."""
    return (
        -uy / UNITY_HEAD_SCALE,  # right
        uz / UNITY_HEAD_SCALE,  # up
        ux / UNITY_HEAD_SCALE,  # anterior (+Z toward camera)
    )


ELECTRODES: list[Electrode] = [
    Electrode(name, *_to_browser_frame(ux, uy, uz))
    for (name, ux, uy, uz) in _UNITY_ELECTRODES
]

# Convenient name -> Electrode lookup.
ELECTRODES_BY_NAME: dict[str, Electrode] = {e.name: e for e in ELECTRODES}


# ---------------------------------------------------------------------------
# CGX channel maps (from lsl_plot_blitting_cgx.py).
#
# CGX streams carry EEG channels followed by reference/aux/accelerometer/packet/
# trigger channels. Visual EEG processors should only consider the EEG channels;
# the rest are ignored unless explicitly enabled.
# ---------------------------------------------------------------------------

# Channels appended after the EEG block on every CGX stream, with their MNE-style
# types. These are NOT scalp EEG and are ignored by visual processors by default.
_CGX_AUX_CHANNELS: list[tuple[str, str]] = [
    ("A2", "misc"),  # extra ground / reference
    ("ExG 1", "emg"),
    ("ExG 2", "emg"),
    ("ACC22", "misc"),  # accelerometer x
    ("ACC23", "misc"),  # accelerometer y
    ("ACC24", "misc"),  # accelerometer z
    ("Packet Count", "misc"),
    ("trigger", "stim"),
]

# CGX Quick20r: 19 EEG channels (27 channels total incl. aux).
_QUICK20R_EEG: list[str] = [
    "F7", "Fp1", "Fp2", "F8", "F3", "Fz", "F4", "C3",
    "Cz", "P8", "P7", "Pz", "P4", "T3", "P3", "O1",
    "O2", "C4", "T4",
]

# CGX Quick32r: 29 EEG channels (37 channels total incl. aux). Matches the
# Unity electrode ordering above.
_QUICK32R_EEG: list[str] = [
    "AF7", "Fpz", "F7", "Fz", "T7", "FC6", "Fp1", "F4", "C4", "Oz",
    "CP6", "Cz", "PO8", "CP5", "O2", "O1", "P3", "P4", "P7", "P8",
    "Pz", "PO7", "T8", "C3", "Fp2", "F3", "F8", "FC5", "AF8",
]


@dataclass(frozen=True)
class CGXMontage:
    """A full CGX channel layout: EEG channels plus trailing aux channels."""

    label: str
    eeg_channel_count: int
    channel_names: list[str]
    channel_types: list[str]  # parallel to channel_names: "eeg" | "emg" | "misc" | "stim"

    @property
    def total_channel_count(self) -> int:
        return len(self.channel_names)

    @property
    def eeg_channel_names(self) -> list[str]:
        return [n for n, t in zip(self.channel_names, self.channel_types) if t == "eeg"]


def _build_montage(label: str, eeg_names: list[str]) -> CGXMontage:
    names = list(eeg_names) + [n for n, _ in _CGX_AUX_CHANNELS]
    types = ["eeg"] * len(eeg_names) + [t for _, t in _CGX_AUX_CHANNELS]
    return CGXMontage(label, len(eeg_names), names, types)


QUICK20R = _build_montage("CGX Quick20r", _QUICK20R_EEG)  # 27 channels total
QUICK32R = _build_montage("CGX Quick32r", _QUICK32R_EEG)  # 37 channels total

# Map total channel count -> montage, for auto-detection from a live stream.
MONTAGE_BY_CHANNEL_COUNT: dict[int, CGXMontage] = {
    QUICK20R.total_channel_count: QUICK20R,
    QUICK32R.total_channel_count: QUICK32R,
}


def montage_for_channel_count(channel_count: int) -> CGXMontage | None:
    """Return the best-known CGX montage for a given total channel count."""
    return MONTAGE_BY_CHANNEL_COUNT.get(channel_count)
