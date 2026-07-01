"""Remap stream channel labels to standard 10-20 / 10-10 electrode names.

Real acquisition streams often expose non-standard channel labels ("EEG1",
"Ch07", vendor codes, ...). A channel map rewrites those to canonical 10-20 names
so everything downstream that keys off the label — the 3D electrode positions,
the region row-sort, per-lobe power — lines up automatically.

The map is a plain ``{raw_label: canonical_name}`` dict. It can be given inline
in the config (``stream.channel_map``) or in a separate file referenced by
``stream.channel_map_file`` (YAML/JSON object, or CSV/TSV rows ``raw,canonical``).
Matching is case- and whitespace-insensitive; when a target is a known electrode
the channel's type is set to ``eeg`` (so a mislabelled misc/aux channel becomes a
real scalp electrode).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assets.electrodes_cgx import ELECTRODES_BY_NAME
from .models import StreamMetadata

# Known electrode names, normalized, for the "target is a real electrode" check.
_KNOWN_ELECTRODES = {name.strip().upper() for name in ELECTRODES_BY_NAME}


def _norm(name: str) -> str:
    """Normalize a label for case/space-insensitive matching."""
    return name.strip().upper()


def load_channel_map(path: str | Path) -> dict[str, str]:
    """Load a channel map from a YAML/JSON object or a CSV/TSV of raw,canonical."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix in (".json",):
        data = json.loads(text)
    elif suffix in (".csv", ".tsv"):
        data = _parse_delimited(text, "\t" if suffix == ".tsv" else ",")
    else:  # .yaml/.yml or anything else -> YAML (a superset of JSON)
        import yaml

        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"channel map {p} must be a mapping of raw->canonical, got {type(data).__name__}"
        )
    return {str(k): str(v) for k, v in data.items()}


def _parse_delimited(text: str, sep: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [c.strip() for c in line.split(sep)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        # Skip an optional header row like "raw,canonical".
        if parts[1].upper() in ("CANONICAL", "NAME", "LABEL", "STANDARD"):
            continue
        mapping[parts[0]] = parts[1]
    return mapping


def resolve_channel_map(
    inline: dict[str, str] | None,
    file: str | Path | None,
) -> dict[str, str]:
    """Merge a file map (base) with an inline map (override); inline wins."""
    merged: dict[str, str] = {}
    if file:
        merged.update(load_channel_map(file))
    if inline:
        merged.update(inline)
    return merged


def apply_channel_map(
    metadata: StreamMetadata, mapping: dict[str, str] | None
) -> StreamMetadata:
    """Rewrite ``metadata.channel_names`` in place using ``mapping`` (raw->canonical).

    Mapped channels whose target is a known electrode are marked type ``eeg``.
    Unmapped channels are left untouched. No-op when the mapping is empty.
    """
    if not mapping:
        return metadata
    norm = {_norm(k): v for k, v in mapping.items()}
    names = list(metadata.channel_names)
    types = list(metadata.channel_types) if metadata.channel_types else None
    for i, name in enumerate(names):
        target = norm.get(_norm(name))
        if target is None:
            continue
        names[i] = target
        if types is not None and i < len(types) and _norm(target) in _KNOWN_ELECTRODES:
            types[i] = "eeg"
    metadata.channel_names = names
    if types is not None:
        metadata.channel_types = types
    return metadata


def coerce_mapping(value: Any) -> dict[str, str]:
    """Normalize a config value into a str->str dict (tolerant of None/empty)."""
    if not value:
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    raise ValueError("channel_map must be a mapping of raw->canonical names")
