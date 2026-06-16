"""10-20 electrode label parsing for regional / hemispheric analyses.

A standard 10-20 label encodes the lobe (letter prefix) and the hemisphere
(trailing number: odd = left, even = right, ``z`` = midline). This module turns
channel-name lists into region/hemisphere groupings and homologous pairs.
"""

from __future__ import annotations

import re

# (prefix -> lobe), checked longest/most-specific first (so FC/CP/PO/TP win over
# F/C/P/T/O).
_PREFIX_LOBE: list[tuple[str, str]] = [
    ("FP", "frontal"),
    ("AF", "frontal"),
    ("FC", "central"),
    ("CP", "central"),
    ("PO", "occipital"),
    ("TP", "temporal"),
    ("F", "frontal"),
    ("C", "central"),
    ("T", "temporal"),
    ("P", "parietal"),
    ("O", "occipital"),
]

# Display/order of lobes for regional outputs.
LOBES: list[str] = ["frontal", "central", "temporal", "parietal", "occipital"]


def _clean(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def parse_label(name: str) -> tuple[str | None, str]:
    """Return ``(lobe, hemisphere)`` for a 10-20 label.

    ``lobe`` is one of :data:`LOBES` (or ``None`` if unrecognised); ``hemisphere``
    is ``"L"``, ``"R"`` or ``"M"`` (midline / unknown).
    """
    s = _clean(name)
    m = re.match(r"([A-Z]+)(Z|\d+)?$", s)
    if not m:
        return None, "M"
    prefix, suffix = m.group(1), m.group(2) or ""
    lobe = next((lb for p, lb in _PREFIX_LOBE if prefix.startswith(p)), None)
    if suffix in ("", "Z"):
        hemi = "M"
    else:
        hemi = "L" if int(suffix) % 2 == 1 else "R"
    return lobe, hemi


def mirror_label(name: str) -> str | None:
    """The homologous (opposite-hemisphere) label, or ``None`` for midline.

    10-20 pairs are (1,2), (3,4), (5,6), (7,8): odd n <-> n+1, even n <-> n-1.
    """
    s = _clean(name)
    m = re.match(r"([A-Z]+)(\d+)$", s)
    if not m:
        return None
    prefix, num = m.group(1), int(m.group(2))
    mirror = num + 1 if num % 2 == 1 else num - 1
    return f"{prefix}{mirror}"


def mirror_indices(names: list[str]) -> list[int]:
    """For each channel, the index of its homologous channel, or -1 if none."""
    idx = {_clean(n): i for i, n in enumerate(names)}
    out: list[int] = []
    for n in names:
        m = mirror_label(n)
        out.append(idx.get(_clean(m), -1) if m else -1)
    return out


def lobe_groups(names: list[str]) -> dict[str, dict[str, list[int]]]:
    """``{lobe: {"L": [idx...], "R": [idx...]}}`` for every recognised lobe."""
    groups: dict[str, dict[str, list[int]]] = {lb: {"L": [], "R": []} for lb in LOBES}
    for i, n in enumerate(names):
        lobe, hemi = parse_label(n)
        if lobe in groups and hemi in ("L", "R"):
            groups[lobe][hemi].append(i)
    return groups
