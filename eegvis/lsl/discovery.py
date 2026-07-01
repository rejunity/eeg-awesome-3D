"""LSL stream discovery.

Thin wrapper over ``pylsl.resolve_streams`` with CGX-friendly filtering. Imports
``pylsl`` lazily so the rest of the app (synthetic mode, server, tests) runs on
machines without liblsl installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import StreamConfig
from ..models import StreamMetadata


class LSLNotAvailable(RuntimeError):
    """Raised when pylsl/liblsl cannot be imported."""


def _import_pylsl():
    try:
        import pylsl  # noqa: WPS433 (intentional lazy import)
    except Exception as exc:  # pragma: no cover - environment dependent
        raise LSLNotAvailable(
            "pylsl is not available. Install it with `pip install pylsl` and "
            "ensure liblsl is on your system (https://github.com/sccn/liblsl). "
            "Or run in synthetic mode with `--synthetic`."
        ) from exc
    return pylsl


@dataclass
class DiscoveredStream:
    metadata: StreamMetadata
    # The underlying pylsl StreamInfo, kept opaque for the receiver to open.
    info: object


def _metadata_from_info(info) -> StreamMetadata:
    """Build a StreamMetadata from a pylsl StreamInfo, including channel labels."""
    channel_names: list[str] = []
    channel_types: list[str] | None = None
    try:
        desc = info.desc()
        ch = desc.child("channels").child("channel")
        names: list[str] = []
        types: list[str] = []
        while not ch.empty():
            label = ch.child_value("label") or ch.child_value("name")
            names.append((label or "").strip())
            types.append((ch.child_value("type") or "").strip().lower())
            ch = ch.next_sibling()
        if names and any(names):
            channel_names = names
            if any(types):
                channel_types = types
    except Exception:
        pass

    if not channel_names:
        channel_names = [f"ch{i}" for i in range(info.channel_count())]

    return StreamMetadata(
        name=info.name(),
        type=info.type(),
        source_id=info.source_id() or None,
        channel_count=info.channel_count(),
        nominal_srate=info.nominal_srate(),
        channel_names=channel_names,
        channel_types=channel_types,
    )


def discover_streams(timeout: float = 2.0) -> list[DiscoveredStream]:
    """Resolve all visible LSL streams (any type)."""
    pylsl = _import_pylsl()
    infos = pylsl.resolve_streams(wait_time=timeout)
    return [DiscoveredStream(_metadata_from_info(i), i) for i in infos]


def choose_stream(
    streams: list[DiscoveredStream], config: StreamConfig
) -> DiscoveredStream | None:
    """Pick the best stream given config filters (type/name/source/CGX-prefer)."""
    candidates = streams

    if config.type:
        typed = [s for s in candidates if s.metadata.type.lower() == config.type.lower()]
        # Fall back to all streams only if no type match exists.
        candidates = typed or candidates

    if config.name:
        candidates = [
            s for s in candidates if config.name.lower() in s.metadata.name.lower()
        ]
    if config.source_id:
        candidates = [s for s in candidates if s.metadata.source_id == config.source_id]

    if not candidates:
        return None

    # Auto-pick default: the stream with the MOST channels wins (a full EEG cap
    # over a smaller / auxiliary stream). Ties break toward a preferred-name (CGX)
    # match, then discovery order. A user-pinned name disables the name preference.
    prefer = "" if config.name else (config.prefer_name_contains or "").lower()

    def _key(item: tuple[int, DiscoveredStream]) -> tuple[int, int, int]:
        idx, s = item
        prefer_match = 1 if prefer and prefer in s.metadata.name.lower() else 0
        return (s.metadata.channel_count, prefer_match, -idx)

    return max(enumerate(candidates), key=_key)[1]
