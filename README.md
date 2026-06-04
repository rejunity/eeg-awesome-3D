# eeg-awesome-3D

Realtime EEG visualisation. Originally a Unity project (Telluride 2024); now
rewritten so the realtime pipeline runs in **Python** and the 3D visualisation
runs in a **local browser app** (Three.js), with no Unity at runtime.

- **Python backend** (`eegvis/`) — discovers/receives the EEG headset over LSL,
  maintains rolling buffers, runs a configurable processing pipeline
  (filters / FFT / band power / normalization / smoothing), serves the app
  locally, and streams processed frames over a WebSocket.
- **Browser frontend** (`web/`) — Vite + TypeScript + Three.js. Renders a 3D
  head/brain with scalp electrodes that react to the processed data, plus a
  scrolling EEG trace and FFT/band display panels.

See [`PLAN.md`](PLAN.md) for the full design and phase breakdown.

---

## Quick start (synthetic data — no hardware needed)

```bash
# 1. Backend deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or: pip install -e .

# 2. Build the frontend once
cd web && npm install && npm run build && cd ..

# 3. Run — opens the browser at http://127.0.0.1:8765/
python -m eegvis run --synthetic
```

You should see a translucent 3D head with electrodes pulsing red→green from the
synthetic signal. Synthetic mode injects sine waves at 6/10/20/40 Hz plus noise
and periodic blink artifacts, so the alpha/beta band displays light up.

If you skip the frontend build, `python -m eegvis run` still starts and serves a
placeholder page explaining how to build it; the WebSocket stream is live
regardless.

## Connecting to a real LSL EEG stream

Real hardware needs `pylsl` and the native `liblsl` library:

```bash
pip install pylsl                       # plus liblsl on your system:
                                        # https://github.com/sccn/liblsl/releases
python -m eegvis list-streams           # see what's visible on the network
python -m eegvis run                    # auto-pick an EEG stream (prefers CGX)
python -m eegvis run --stream-name CGX  # or pin one by name
python -m eegvis inspect-stream --stream-type EEG   # dump channel layout
```

The receiver auto-detects CGX montages by channel count: **27 channels** →
Quick20r (19 EEG), **37 channels** → Quick32r (29 EEG). Non-EEG channels
(reference, ExG, accelerometer, packet count, trigger) are ignored by the visual
processors. If no stream is found the app reports it clearly and keeps retrying;
add `--synthetic` to fall back to synthetic data.

The server exits a few seconds after you close the browser tab (the last
WebSocket client disconnects). Page reloads reconnect within the grace window
and keep it running; `--no-browser`/headless runs stay up. Disable with
`exit_on_browser_close: false` in config.

## Replaying real recordings (no hardware)

You can replay a real public EEG recording as an LSL source:

```bash
python -m eegvis fetch-sample            # download + prepare a PhysioNet recording
python -m eegvis play-file recordings/S001R03_cgx.npz   # stream it over LSL
python -m eegvis run                     # in another terminal: connect to it
```

`play-file` also accepts a raw `.edf` directly. Data provenance, the channel
mapping onto the CGX montage, and a survey of other public datasets are in
[docs/recordings.md](docs/recordings.md).

### CLI reference

```bash
python -m eegvis run [--synthetic] [--no-browser] [--stream-type EEG]
                     [--stream-name NAME] [--host H] [--port P] [--config FILE]
python -m eegvis list-streams
python -m eegvis inspect-stream [--stream-type EEG] [--stream-name NAME]
```

## Frontend development

For live frontend work, run the Vite dev server (it proxies `/api` and `/ws`
back to the Python backend on port 8765):

```bash
python -m eegvis run --synthetic --no-browser   # terminal 1: backend
cd web && npm run dev                            # terminal 2: Vite @ :5173
```

### Controls

Keyboard (mirrors the original Unity `Controls.cs`):

| Key     | Action                              |
|---------|-------------------------------------|
| `Space` | toggle electrode indicators         |
| `Z`     | EEG strip / trace display           |
| `X`     | electrode/band display              |
| `C`     | FFT display                         |
| `1`–`7` | visual presets                      |
| `↑`/`↓` | head cutaway / transparency         |

There is also a lil-gui panel (top right) for preset, colour mode, band, head
opacity, trace invert, auto-rotate, and a debug-electrode isolator.

---

## Architecture

```
EEG headset ──LSL──▶ Python backend ──WebSocket JSON──▶ Browser (Three.js)
                     │
                     ├─ lsl/        discovery + StreamInlet receiver (own thread)
                     │              + synthetic generator
                     ├─ processing/ rolling buffer + plugin pipeline
                     ├─ server/     FastAPI: / , /api/status, /api/config,
                     │              /api/electrodes, /ws/eeg + the engine loop
                     └─ assets/     CGX electrode metadata + default config
```

LSL sampling, processing/broadcast, and browser rendering are decoupled: the
receiver thread fills a queue; an asyncio engine ticks at `output_hz` (default
30), runs the pipeline, and broadcasts only the latest frame (stale frames are
dropped, never queued).

### WebSocket payloads

`status` on connect, then `eeg_frame` at `output_hz`. See `eegvis/models.py`
for the exact Pydantic contract (`StatusPayload`, `EEGFramePayload`); the
TypeScript mirror is `web/src/net/protocol.ts`. Both carry `schema_version`.

### Configuration

Defaults live in `eegvis/assets/default_config.yaml`. Override with
`--config my.yaml` (deep-merged over defaults); CLI flags win over both. The
config controls server host/port, stream filters, the processor chain, and
synthetic-data parameters.

## Adding a processor

Processors are small, independent, testable units. To add one:

1. Subclass `EEGProcessor` (`eegvis/processing/base.py`), set `name` and
   `output_keys`, implement `configure()`, `reset()`, and `process()`.
   `process()` reads the rolling `ProcessingState` and returns a dict of
   serializable output keys merged into the frame.
2. Register it in `eegvis/processing/registry.py` (one line).
3. Add a config block under `processing.processors` in the YAML.

The LSL receiver and WebSocket code never change. Processors operate on NumPy
arrays and must not know about WebSockets or Three.js. Keep scientific values
separate from display normalization. See `normalization.py` / `band_power.py`
as templates, and `short_fourier.py` for a visual-parity processor that mirrors
the Unity short-Fourier effect.

## Tests

```bash
pip install pytest httpx
python -m pytest          # 16 tests: config, payloads, synthetic stream,
                          # processors (alpha@10Hz, beta@20Hz, FFT peak),
                          # and the WebSocket frame stream in synthetic mode
```

## Troubleshooting

- **`pylsl is not available` / liblsl errors** — install `liblsl` for your OS
  (https://github.com/sccn/liblsl/releases) and `pip install pylsl`. Synthetic
  mode (`--synthetic`) needs neither.
- **No stream found** — `python -m eegvis list-streams` to confirm the headset
  is publishing; check it's on the same network/LSL session.
- **Browser shows the placeholder page** — build the frontend (`cd web &&
  npm run build`) or use the Vite dev server.
- **Random test data** — `python -m pylsl.examples.SendDataAdvanced` publishes a
  synthetic LSL stream you can point `python -m eegvis run` at.

## What was ported from the Unity reference

The Unity project (`EEGViewer-Unity/`) is kept as the visual/behavioural
reference. Ported into the new app:

- CGX electrode names + 3D positions from `LSLInletReader.cs` →
  `eegvis/assets/electrodes_cgx.py` (converted to a normalized Y-up,
  +Z-anterior browser frame; see the module docstring for the conversion).
- 27/37-channel CGX montages (EEG vs aux) from `lsl_plot_blitting_cgx.py`.
- Moving min/max normalization and the short-Fourier 10/20/40 Hz visual effect
  from `LSLInletReader.cs`.
- Red→green electrode colour mapping (`MixEEGColors`), the scrolling EEG strip
  (`PlotPixel.compute` / eegDisplayRT), and the FFT/band texture workflow,
  re-expressed with browser-native canvas textures.
- Keyboard controls and the 7 visual presets from `Controls.cs`.

### Asset conversion (head / brain models)

The browser currently renders a **procedural** head ellipsoid + brain mesh
fallback. To use the original models, convert them to glTF and drop them in
`web/public/models/`:

- `Realistic_Brain.fbx` → `brain.glb`
- `Realistic_White_Female_Head.obj` → `head.glb`

Export via Blender (File → Import the FBX/OBJ, then File → Export → glTF 2.0
`.glb`), then load them with `GLTFLoader` in `web/src/scene/brainHead.ts`.
Brain models by **Dean Lavery** (CC Attribution):
- https://sketchfab.com/3d-models/brain-areas-d64608a3978b47d8a39c5a15795ca8c4
- https://sketchfab.com/3d-models/brain-project-24ec03412dd8432bb0d3e750a72608e0

---

## Legacy Unity version

The original Unity project lives in `EEGViewer-Unity/` and is **not required**
for the browser app. Slide deck:
https://docs.google.com/presentation/d/1xzQ1zwIQPY_zxPfgCSPdW2VmvVi7m97dMNGVeG4rU6c/edit

To run the legacy version: this repo uses Git LFS
(https://docs.github.com/en/repositories/working-with-files/managing-large-files/installing-git-large-file-storage).
Install `liblsl` + `pylsl`, run `python -m pylsl.examples.SendDataAdvanced` for
test data, open the project in Unity, and press Play.
