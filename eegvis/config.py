"""Configuration loading and typed config models.

Config sources, lowest to highest precedence:

1. ``eegvis/assets/default_config.yaml`` (bundled defaults).
2. An optional user YAML file passed with ``--config``.
3. CLI flag overrides applied in ``cli.py``.
"""

from __future__ import annotations

import copy
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_RESOURCE = "default_config.yaml"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True
    # Shut the server down shortly after the browser tab is closed (i.e. the
    # last WebSocket client disconnects and doesn't reconnect within the grace
    # period). Only arms after the first client has connected, so headless /
    # --no-browser runs stay up.
    exit_on_browser_close: bool = True
    idle_shutdown_grace: float = 3.0


class StreamConfig(BaseModel):
    type: str = "EEG"
    name: str | None = None
    source_id: str | None = None
    # Auto-pick default picks the stream with the most channels; this substring
    # only breaks ties (equal channel count) toward a preferred-name match.
    prefer_name_contains: str | None = "cgx"
    resolve_timeout: float = 5.0
    synthetic_fallback: bool = False
    # Remap raw stream channel labels -> standard 10-20/10-10 names. Inline map
    # merged over an optional external file (YAML/JSON object, or CSV/TSV rows
    # "raw,canonical"); inline entries win. Applied to every source's metadata.
    channel_map: dict[str, str] = Field(default_factory=dict)
    channel_map_file: str | None = None


class ProcessorConfig(BaseModel):
    """One processor entry; extra keys are processor-specific and kept as-is."""

    model_config = {"extra": "allow"}

    name: str
    enabled: bool = True

    def options(self) -> dict[str, Any]:
        """Processor-specific options (everything except name/enabled)."""
        return {
            k: v
            for k, v in self.model_dump().items()
            if k not in ("name", "enabled")
        }


class ProcessingConfig(BaseModel):
    output_hz: float = 30.0
    rolling_window_seconds: float = 10.0
    # Global processor run cadence (applies to all processors):
    #   "realtime" | "per-sample" -> run every tick that has new samples
    #   "frequency"               -> run at most run_hz times per second
    run_mode: str = "realtime"
    run_hz: float = 30.0
    # Built-in common-average-reference (spatial) filter, head of the chain.
    # Off for programmatic use; the bundled default_config turns it on.
    car: bool = False
    # The ordered global filter chain (signal -> signal), applied before the
    # extractors and producing the `filtered` window they read. The built-in
    # notch + bandpass front-end is always present and runtime-controllable;
    # these are EXTRA filters appended after it (e.g. {name: car}).
    filters: list[ProcessorConfig] = Field(default_factory=list)
    # The extractor fan-out (signal -> features); order-independent.
    processors: list[ProcessorConfig] = Field(default_factory=list)


class SyntheticConfig(BaseModel):
    channel_count: int = 37
    sample_rate: float = 250.0
    frequencies: list[float] = Field(default_factory=lambda: [6, 10, 20, 40])
    amplitudes: list[float] = Field(default_factory=lambda: [1.0, 0.8, 0.5, 0.3])
    noise: float = 0.15
    blink_artifacts: bool = True
    # Optional common-mode mains hum (for demonstrating the notch / CAR). Off by
    # default; toggled live from the GUI debug pane.
    mains_hum: bool = False
    mains_hz: float = 50.0
    mains_amplitude: float = 0.6


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    stream: StreamConfig = Field(default_factory=StreamConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    synthetic: SyntheticConfig = Field(default_factory=SyntheticConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_default_dict() -> dict[str, Any]:
    text = (
        resources.files("eegvis.assets")
        .joinpath(DEFAULT_CONFIG_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return yaml.safe_load(text) or {}


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load the default config, optionally merged with a user override file."""
    data = _load_default_dict()
    if config_path is not None:
        user_text = Path(config_path).read_text(encoding="utf-8")
        user_data = yaml.safe_load(user_text) or {}
        data = _deep_merge(data, user_data)
    config = AppConfig.model_validate(data)
    _resolve_channel_map(config)
    return config


def _resolve_channel_map(config: AppConfig) -> None:
    """Fold ``stream.channel_map_file`` into ``stream.channel_map`` (inline wins)."""
    from .channel_map import resolve_channel_map

    stream = config.stream
    if stream.channel_map or stream.channel_map_file:
        stream.channel_map = resolve_channel_map(
            stream.channel_map, stream.channel_map_file
        )
