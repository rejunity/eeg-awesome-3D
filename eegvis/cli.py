"""Command-line interface for eegvis.

    python -m eegvis run                 # connect to LSL EEG, open browser
    python -m eegvis run --synthetic     # synthetic data, no hardware needed
    python -m eegvis run --no-browser
    python -m eegvis list-streams        # debug: print visible LSL streams
    python -m eegvis inspect-stream --stream-type EEG
"""

from __future__ import annotations

import threading
import time
import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import AppConfig, load_config

app = typer.Typer(add_completion=False, help="Realtime EEG -> browser visualiser.")
console = Console()


def _apply_overrides(
    config: AppConfig,
    *,
    synthetic: bool | None = None,
    stream_type: str | None = None,
    stream_name: str | None = None,
    no_browser: bool = False,
    host: str | None = None,
    port: int | None = None,
) -> AppConfig:
    if stream_type is not None:
        config.stream.type = stream_type
    if stream_name is not None:
        config.stream.name = stream_name
    if synthetic:
        config.stream.synthetic_fallback = True
    if no_browser:
        config.server.open_browser = False
    if host is not None:
        config.server.host = host
    if port is not None:
        config.server.port = port
    return config


@app.command()
def run(
    synthetic: bool = typer.Option(False, "--synthetic", help="Use synthetic data."),
    stream_type: str = typer.Option(None, "--stream-type", help="LSL stream type filter."),
    stream_name: str = typer.Option(None, "--stream-name", help="LSL stream name filter."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser."),
    host: str = typer.Option(None, "--host", help="Bind host (default 127.0.0.1)."),
    port: int = typer.Option(None, "--port", help="Bind port (default 8765)."),
    config_path: Path = typer.Option(None, "--config", help="User config YAML override."),
) -> None:
    """Start the local server, data source, and (optionally) the browser."""
    import uvicorn

    from .server.app import create_app

    config = load_config(config_path)
    config = _apply_overrides(
        config,
        synthetic=synthetic,
        stream_type=stream_type,
        stream_name=stream_name,
        no_browser=no_browser,
        host=host,
        port=port,
    )

    url = f"http://{config.server.host}:{config.server.port}/"
    mode = "synthetic" if synthetic else "LSL (synthetic fallback: %s)" % config.stream.synthetic_fallback
    console.print(f"[bold green]eegvis[/] starting — mode: {mode}")
    console.print(f"Serving at [link={url}]{url}[/]  ·  WebSocket: ws://{config.server.host}:{config.server.port}/ws/eeg")

    if config.server.open_browser:
        _open_browser_when_ready(url)

    fastapi_app = create_app(config, synthetic=synthetic)
    uvicorn.run(fastapi_app, host=config.server.host, port=config.server.port, log_level="warning")


def _open_browser_when_ready(url: str, delay: float = 1.0) -> None:
    """Open the browser shortly after the server starts (in a background thread)."""

    def _open() -> None:
        time.sleep(delay)
        webbrowser.open_new_tab(url)

    threading.Thread(target=_open, daemon=True).start()


@app.command("list-streams")
def list_streams(
    timeout: float = typer.Option(2.0, help="Seconds to wait for streams."),
) -> None:
    """Print all visible LSL streams."""
    from .lsl.discovery import LSLNotAvailable, discover_streams

    try:
        streams = discover_streams(timeout=timeout)
    except LSLNotAvailable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    if not streams:
        console.print("[yellow]No LSL streams found.[/]")
        return

    table = Table(title="LSL streams")
    for col in ("Name", "Type", "Channels", "Rate (Hz)", "Source ID"):
        table.add_column(col)
    for s in streams:
        m = s.metadata
        table.add_row(m.name, m.type, str(m.channel_count), f"{m.nominal_srate:g}", m.source_id or "")
    console.print(table)


@app.command("inspect-stream")
def inspect_stream(
    stream_type: str = typer.Option("EEG", "--stream-type", help="Stream type filter."),
    stream_name: str = typer.Option(None, "--stream-name", help="Stream name filter."),
    timeout: float = typer.Option(2.0, help="Seconds to wait."),
) -> None:
    """Resolve a stream and print its channel layout."""
    from .lsl.discovery import LSLNotAvailable, choose_stream, discover_streams

    config = load_config()
    config.stream.type = stream_type
    config.stream.name = stream_name

    try:
        streams = discover_streams(timeout=timeout)
    except LSLNotAvailable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    chosen = choose_stream(streams, config.stream)
    if chosen is None:
        console.print("[yellow]No matching stream found.[/]")
        raise typer.Exit(code=1)

    m = chosen.metadata
    console.print(f"[bold]{m.name}[/] ({m.type}) — {m.channel_count} ch @ {m.nominal_srate:g} Hz")
    table = Table(title="Channels")
    table.add_column("#")
    table.add_column("Label")
    table.add_column("Type")
    types = m.channel_types or ["?"] * m.channel_count
    for i, name in enumerate(m.channel_names):
        table.add_row(str(i), name, types[i] if i < len(types) else "?")
    console.print(table)


@app.command("fetch-sample")
def fetch_sample(
    subject: int = typer.Option(1, help="eegmmidb subject number."),
    run: int = typer.Option(3, help="eegmmidb run number (e.g. 3 = a task run)."),
) -> None:
    """Download a public EEG recording and map it to the CGX channels.

    Uses the PhysioNet EEG Motor Movement/Imagery DB (64-ch 10-10, 160 Hz),
    saving a prepared .npz under ./recordings ready for `play-file`.
    """
    from .recordings.download import fetch_eegmmidb

    console.print(f"Downloading eegmmidb S{subject:03d}R{run:02d} from PhysioNet…")
    npz_path, prep = fetch_eegmmidb(subject=subject, run=run)
    console.print(
        f"[green]Prepared[/] {npz_path} — {prep.data.shape[0]} samples @ "
        f"{prep.sample_rate:g} Hz, {len(prep.matched)}/{len(prep.channel_names)} "
        f"CGX channels matched."
    )
    if prep.missing:
        console.print(f"[yellow]Missing (zero-filled):[/] {', '.join(prep.missing)}")


@app.command("play-file")
def play_file(
    path: Path = typer.Argument(..., help="Recording to replay (.edf or prepared .npz)."),
    name: str = typer.Option("eegvis-replay", help="LSL stream name to advertise."),
    loop: bool = typer.Option(True, help="Loop the recording when it ends."),
) -> None:
    """Replay a recording as an LSL EEG source (connect with `eegvis run`)."""
    from .lsl.player import play_recording
    from .lsl.discovery import LSLNotAvailable

    console.print(f"Streaming [bold]{path}[/] as LSL stream '{name}' (Ctrl-C to stop)…")
    try:
        play_recording(path, name=name, loop=loop)
    except LSLNotAvailable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\nStopped.")


if __name__ == "__main__":
    app()
