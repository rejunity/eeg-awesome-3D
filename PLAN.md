# PLAN.md — EEG Awesome 3D browser + Python rewrite

## Purpose

This project should be rewritten so the realtime EEG pipeline runs in Python and the 3D visualisation runs in a local native browser app, without Unity at runtime.

The existing Unity project is the visual and behavioural reference. Do not copy Unity architecture forward. Treat the Unity code, shaders, electrode positions, models, and interaction modes as reference material to recreate in a browser-first architecture.

## Primary goals

1. Port the 3D visualisation from Unity to a local browser app.
2. Move LSL stream discovery/receiving out of Unity and into Python.
3. Make Python responsible for:
   - discovering and connecting to the EEG headset via LSL,
   - receiving EEG chunks,
   - maintaining rolling buffers,
   - processing data with filters, FFT, band power, smoothing, normalization, and future processors,
   - serving the browser app locally,
   - opening the browser automatically,
   - streaming processed data to the browser in realtime.
4. Make the browser responsible for:
   - 3D rendering,
   - electrode/head/brain visuals,
   - realtime animation from processed values,
   - UI controls and visual presets.
5. Make Python data processors easy to add, remove, configure, and test.
6. Preserve the original visual feel: head/brain model, scalp electrodes, color-reactive electrode indicators, scrolling EEG texture/strip chart, FFT/band display modes, and keyboard/preset controls.

## Non-goals for the first pass

- Do not run Unity in production.
- Do not receive LSL directly in the browser.
- Do not build a remote/cloud service. Default to localhost.
- Do not over-optimize binary protocols before the JSON/WebSocket MVP works.
- Do not require the EEG headset for development; support synthetic data mode from day one.
- Do not delete the old Unity project until the browser visualisation reaches functional parity.

## Existing project reference points

Use these existing files as reference while implementing:

- `README.md`
  - Existing setup notes mention `liblsl`, `pylsl`, and testing with pylsl random data.
- `ReceiveAndPlot.py`
  - Existing Python example for pulling LSL streams and plotting continuous channels.
- `read_lsl_streams.py`
  - Existing minimal LSL stream discovery and chunk pulling example.
- `lsl_plot_blitting_cgx.py`
  - Existing CGX-specific Python/MNE exploration, channel maps, and realtime plotting ideas.
- `EEGViewer-Unity/Assets/LSLInletReader.cs`
  - Main Unity LSL reader and visual driver.
  - Contains CGX electrode names and 3D electrode positions.
  - Contains moving min/max normalization, random fallback data, short Fourier mode, computed Fourier mode, electrode color updates, EEG strip texture updates, and electrode/FFT render texture updates.
- `EEGViewer-Unity/Assets/Controls.cs`
  - Reference for keyboard controls and visual setup switching.
- `EEGViewer-Unity/Assets/Electrode.cs`
  - Reference for positioning electrode effects against the head/skull surface.
- `EEGViewer-Unity/Assets/DisplayEEG.cs`
  - Reference for full-screen display of generated EEG/electrode textures.
- `EEGViewer-Unity/Assets/PlotPixel.compute`
  - Reference for EEG strip plotting, texture fade/bar drawing, FFT-style texture updates.
- `EEGViewer-Unity/Assets/ElectrodeDisplay.shader`
  - Reference for electrode display material behaviour.
- `EEGViewer-Unity/Assets/HumanHead.shader`
  - Reference for head cutaway/cutoff behaviour.
- `EEGViewer-Unity/Assets/Realistic_Brain.fbx`
  - Brain model to migrate or convert for browser rendering.
- `EEGViewer-Unity/Assets/Realistic_White_Female_Head.obj`
  - Head model to migrate or convert for browser rendering.
- `EEGViewer-Unity/Assets/cgx-electrode-map.png`
  - Reference for CGX electrode placement and labelling.

## Proposed architecture

```text
                      ┌────────────────────────────────────┐
                      │           EEG headset / LSL         │
                      └──────────────────┬─────────────────┘
                                         │ LSL
                                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                          Python backend                           │
│                                                                  │
│  cli.py                                                          │
│   ├─ starts local server                                          │
│   ├─ opens browser                                                │
│   └─ chooses real LSL or synthetic mode                           │
│                                                                  │
│  lsl/receiver.py                                                  │
│   ├─ discovers EEG streams                                        │
│   ├─ connects with pylsl.StreamInlet                              │
│   ├─ pulls chunks into rolling buffer                             │
│   └─ emits EEGChunk objects                                       │
│                                                                  │
│  processing/pipeline.py                                           │
│   ├─ plugin registry                                              │
│   ├─ rolling windows                                              │
│   ├─ normalization                                                │
│   ├─ filters / FFT / band powers                                  │
│   └─ emits compact EEGFrame payloads                              │
│                                                                  │
│  server/app.py                                                    │
│   ├─ serves browser frontend                                      │
│   ├─ WebSocket endpoint /ws/eeg                                   │
│   ├─ status endpoint /api/status                                  │
│   └─ config endpoint /api/config                                  │
└──────────────────────────────────────────────────────────────────┘
                                         │ WebSocket JSON first,
                                         │ optional msgpack later
                                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Browser frontend                          │
│                                                                  │
│  Vite + TypeScript + Three.js                                     │
│   ├─ websocket client                                             │
│   ├─ shared payload types                                         │
│   ├─ 3D head/brain scene                                          │
│   ├─ electrode markers and indicators                             │
│   ├─ EEG trace canvas/texture                                     │
│   ├─ band/FFT texture panels                                      │
│   ├─ controls/presets                                             │
│   └─ render loop driven by latest processed EEGFrame              │
└──────────────────────────────────────────────────────────────────┘
```

## Recommended repository layout

Create the new application beside the legacy Unity project first. Do not remove the Unity folder until parity is confirmed.

```text
.
├── PLAN.md
├── README.md
├── pyproject.toml
├── eegvis/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── lsl/
│   │   ├── __init__.py
│   │   ├── discovery.py
│   │   ├── receiver.py
│   │   └── synthetic.py
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── pipeline.py
│   │   ├── registry.py
│   │   ├── normalization.py
│   │   ├── filters.py
│   │   ├── fft.py
│   │   ├── band_power.py
│   │   └── smoothing.py
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── websocket.py
│   │   └── static.py
│   └── assets/
│       ├── electrodes_cgx.py
│       └── default_config.yaml
├── web/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── app.ts
│       ├── net/
│       │   ├── websocket.ts
│       │   └── protocol.ts
│       ├── scene/
│       │   ├── createScene.ts
│       │   ├── brainHead.ts
│       │   ├── electrodes.ts
│       │   ├── eegTraceTexture.ts
│       │   ├── bandTexture.ts
│       │   └── presets.ts
│       ├── controls/
│       │   ├── keyboard.ts
│       │   └── gui.ts
│       └── assets/
│           ├── models/
│           │   ├── brain.glb
│           │   └── head.glb
│           └── textures/
├── tests/
│   ├── test_processors.py
│   ├── test_protocol.py
│   ├── test_synthetic_stream.py
│   └── test_lsl_discovery.py
└── legacy/
    └── optional-notes.md
```

If moving existing files is too disruptive, keep `EEGViewer-Unity/` where it is and create the Python/browser structure at repo root.

## Technology choices

### Backend

Use Python 3.11+.

Core dependencies:

- `pylsl` for LSL discovery and data receiving.
- `numpy` for buffers and FFT preparation.
- `scipy` for filters and signal utilities.
- `fastapi` for local HTTP/WebSocket server.
- `uvicorn` for serving the local app.
- `pydantic` for typed payload/config models.
- `pydantic-settings` or YAML config loading for runtime configuration.
- `typer` or `argparse` for CLI.
- `rich` for clear terminal status output.

Optional dependencies:

- `mne` for montage/channel metadata if useful.
- `msgpack` only after JSON WebSocket payloads work.
- `watchfiles` for development auto-reload.

Create or update requirements.txt for pip installation. Keep it always up to date.

### Frontend

Use Vite + TypeScript + Three.js.

Core dependencies:

- `three` for WebGL scene rendering.
- Vite for local browser app build/dev server.
- `lil-gui` or equivalent for quick runtime controls.

Avoid a large frontend framework unless there is a clear need. The application is primarily a realtime canvas/WebGL app, so TypeScript modules plus Three.js are enough for the MVP.

## Local startup behaviour

The preferred user command should be:

```bash
python -m eegvis run
```

Default behaviour:

1. Load config from `eegvis/assets/default_config.yaml`, then optional user override.
2. Start FastAPI/uvicorn bound to `127.0.0.1` on a default port, for example `8765`.
3. Start LSL discovery in Python.
4. If no EEG stream is found within the configured timeout, either:
   - continue in synthetic mode if `--synthetic` is set, or
   - show clear terminal instructions and keep retrying if configured.
5. Open the browser automatically at `http://127.0.0.1:8765/` using Python `webbrowser.open_new_tab`.
6. Browser connects to `ws://127.0.0.1:8765/ws/eeg`.
7. Browser shows connection status, stream metadata, and live visualisation.

CLI examples:

```bash
python -m eegvis run
python -m eegvis run --synthetic
python -m eegvis run --stream-type EEG
python -m eegvis run --stream-name "CGX"
python -m eegvis run --no-browser
python -m eegvis list-streams
python -m eegvis inspect-stream --stream-type EEG
```

## Backend implementation details

### Data models

Create typed models in `eegvis/models.py`.

Suggested core models:

```python
@dataclass
class StreamMetadata:
    name: str
    type: str
    source_id: str | None
    channel_count: int
    nominal_srate: float
    channel_names: list[str]
    channel_types: list[str] | None = None

@dataclass
class EEGChunk:
    data: np.ndarray          # shape: samples x channels
    timestamps: np.ndarray    # shape: samples
    metadata: StreamMetadata

@dataclass
class ProcessingState:
    sample_rate: float
    channel_names: list[str]
    rolling_data: np.ndarray
    rolling_timestamps: np.ndarray
    frame_index: int
```

For WebSocket payloads, use Pydantic models so they serialize cleanly.

### WebSocket payload contract

Start with JSON. Keep payloads compact and stable.

Status payload:

```json
{
  "type": "status",
  "connected": true,
  "mode": "lsl",
  "stream": {
    "name": "...",
    "type": "EEG",
    "source_id": "...",
    "channel_count": 29,
    "sample_rate": 500,
    "channel_names": ["AF7", "Fpz", "F7"]
  }
}
```

Realtime frame payload:

```json
{
  "type": "eeg_frame",
  "frame_index": 1234,
  "timestamp": 123456.789,
  "sample_rate": 500,
  "channels": ["AF7", "Fpz", "F7"],
  "latest": [0.12, -0.05, 0.3],
  "normalized": [0.56, 0.48, 0.64],
  "bands": {
    "delta": [0.1, 0.2, 0.1],
    "theta": [0.2, 0.1, 0.2],
    "alpha": [0.6, 0.4, 0.7],
    "beta": [0.3, 0.2, 0.4],
    "gamma": [0.1, 0.1, 0.1]
  },
  "fft": {
    "freqs": [1, 2, 3, 4, 5],
    "values": [[0.1, 0.2, 0.3, 0.2, 0.1]]
  },
  "quality": {
    "samples_received": 250000,
    "dropped_chunks": 0,
    "latency_ms": 20
  }
}
```

Rules:

- `latest` should contain latest raw or scaled values per channel.
- `normalized` should be per-channel normalized values suitable for direct colour/scale animation.
- `bands` should contain per-channel band powers normalized for visualisation.
- `fft` can be downsampled and sent less often if too large.
- Avoid sending full rolling raw buffers every frame.
- Add a `schema_version` field if the protocol starts changing frequently.

### LSL discovery and receiving

Implement `eegvis/lsl/discovery.py`:

- Search by stream type first: `EEG`.
- Allow stream name/source filters from config/CLI.
- Print all discovered streams with name, type, channel count, sample rate, source id.
- Prefer a CGX stream if stream name contains `cgx` and the user has not specified another stream.
- Provide `list-streams` CLI for debugging.

Implement `eegvis/lsl/receiver.py`:

- Use `pylsl.StreamInlet`.
- Pull chunks with a short timeout or nonblocking pattern.
- Use a rolling buffer with a configurable window size, for example 5–10 seconds.
- Preserve timestamps.
- Emit `EEGChunk` objects into an asyncio queue or thread-safe queue.
- Make reconnection explicit: if the stream disappears, send status update and retry discovery.

Important: keep LSL pulling and WebSocket broadcasting decoupled. The visual framerate should not control the LSL sampling loop.

### Synthetic data mode

Implement `eegvis/lsl/synthetic.py` immediately.

It should generate channel data with:

- sine waves at known frequencies, for example 6 Hz, 10 Hz, 20 Hz, 40 Hz,
- per-channel phase offsets,
- optional noise,
- optional simulated blink/motion artifacts,
- CGX-like channel names.

Use synthetic mode for frontend development and automated tests.

### CGX electrode metadata

Extract the CGX Quick32r electrode names and 3D positions from the Unity `LSLInletReader.cs` reference into `eegvis/assets/electrodes_cgx.py` and a frontend equivalent JSON file.

Normalize positions into a browser-friendly coordinate system:

- Convert Unity coordinates to a unit-ish head coordinate space.
- Keep a single documented scale factor.
- Validate labels match received channel names.
- If the stream has 27 channels, use the Quick20r mapping from existing Python reference where available.
- If the stream has 37 channels, use the Quick32r mapping from existing Python reference and Unity electrode positions.
- Extra non-EEG channels such as accelerometer, packet count, trigger, and aux channels should be ignored by visual EEG processors unless explicitly enabled.

### Processing pipeline

Orthogonal architecture — two distinct node kinds and two windows:

```
raw window ─► notch ─► bandpass ─► (extra filters) ─► filtered window ─► extractors (fan-out) ─► frame
                  the FILTER CHAIN (ordered, stateful, runs every tick)         band_power, fft, hjorth,
   raw trace (X) ◄── raw window      filtered trace (Z) + electrodes ◄──┘       line_length, entropy, …
```

- **Filters** (`processing.filters` + the built-in `notch`→`bandpass` front-end):
  signal→signal, an ordered stateful chain that runs every tick and writes the
  `filtered` window. The raw window is never mutated (the raw trace stays raw).
  The single band selector (none / delta…gamma / custom) drives the global
  bandpass — there is no separate visual-only band. `custom` uses the low/high
  controls, and **low > high reverses it to a band-stop** (reject that band). The
  front-end is off by default and controlled live (GUI "Filters (global)" /
  `set_bandpass`, `set_notch`); it feeds the trace, electrodes and every extractor.
- **Extractors** (`processing.processors`): signal→features, an
  order-independent fan-out; each reads `filtered` by default or `raw` via
  `input: raw|filtered`. No extractor reads another's output.
- **Electrodes** colour by a selectable source (GUI "Electrode source"): the
  filtered `signal`, or any per-channel band-power / feature value from the frame.
- The **FFT** spectrum defaults to the `filtered` window (reflects the chain);
  toggle its source to `raw` (GUI "FFT source") to see the full input spectrum.
  The per-sample `filtered_samples` stream feeds the processed trace.

Create a plugin-friendly processing pipeline.

Base processor interface:

```python
class EEGProcessor(Protocol):
    name: str
    enabled: bool

    def configure(self, config: dict[str, Any], metadata: StreamMetadata) -> None:
        ...

    def reset(self) -> None:
        ...

    def process(self, chunk: EEGChunk, state: ProcessingState) -> dict[str, Any]:
        ...
```

Processor registry:

```python
PROCESSORS = {
    "normalization": NormalizationProcessor,
    "bandpass": BandpassProcessor,
    "fft": FFTProcessor,
    "band_power": BandPowerProcessor,
    "smoothing": SmoothingProcessor,
}
```

Pipeline config example:

```yaml
processing:
  output_hz: 30
  rolling_window_seconds: 5
  processors:
    - name: bandpass
      enabled: true
      low_hz: 1.0
      high_hz: 45.0
      order: 4
    - name: notch
      enabled: false
      hz: 50.0
    - name: normalization
      enabled: true
      method: moving_minmax
      reactivity: 0.9
    - name: fft
      enabled: true
      window_seconds: 1.0
      update_hz: 10
    - name: band_power
      enabled: true
      bands:
        delta: [1, 4]
        theta: [4, 8]
        alpha: [8, 13]
        beta: [13, 30]
        gamma: [30, 45]
    - name: smoothing
      enabled: true
      method: exponential
      alpha: 0.25
```

Processor rules:

- Processors must be independent and testable.
- Processors must declare their output keys.
- Processors should not know about WebSocket clients or Three.js.
- Processors should operate on NumPy arrays and return serializable arrays/lists for payload assembly.
- Avoid mutating input chunks unless clearly documented.
- Keep display normalization separate from scientific raw values.

### Required processors for MVP

1. `NormalizationProcessor`
   - Moving min/max normalization similar to Unity.
   - Optional z-score mode.
   - Output `normalized` in approximately `[0, 1]` or `[-1, 1]`, document which one is used.

2. `BandpassProcessor`
   - Configurable low/high cutoff.
   - Use second-order sections internally.
   - Preserve state for realtime filtering instead of recomputing everything from scratch.

3. `FFTProcessor`
   - Uses rolling window.
   - Uses Hann window.
   - Uses `np.fft.rfft` or SciPy equivalent.
   - Sends compact frequency bins and values.

4. `BandPowerProcessor`
   - Computes delta/theta/alpha/beta/gamma band powers.
   - Supports custom band definitions.
   - Normalizes for visual display.

5. `SmoothingProcessor`
   - Exponential smoothing for visual stability.
   - Configurable alpha/reactivity.

6. `ShortFourierVisualProcessor`
   - Recreate the Unity short Fourier visual feel: three main bands/oscillators around 10 Hz, 20 Hz, and 40 Hz, mapped to colour channels or display bands.
   - It does not need to be scientifically perfect; it is a visual parity processor.

### EEG filters and feature extractors (curated reference)

A survey of the filters and features that dominate EEG literature, scoped to what
is useful and feasible in a real-time visualiser. Each processor is a pure
function of the global rolling window (feature extractors) or a streaming
transform of it (preprocessing filters). Implemented ones are marked ✓.

Preprocessing filters (clean the signal before feature extraction):

- ✓ **Band-pass** (IIR Butterworth, SOS) — universal first step, ~0.5–45 Hz.
- ✓ **Notch / band-stop** at 50/60 Hz (+ harmonics) — mains line noise.
- ✓ **Common Average Reference (CAR)** — subtract the cross-channel mean per
  sample; cheap spatial filter, very common, real-time friendly.
- Surface Laplacian / CSD, ICA, ASR — stronger artifact/spatial methods; offline
  or heavier, deferred.

Feature extractors:

- Time domain (cheap, per channel)
  - ✓ **Hjorth parameters** — activity (variance), mobility, complexity.
  - ✓ **Line length** — sum of |Δx|; popular for seizure/burst detection.
  - ✓ RMS / variance / skewness / kurtosis (covered by Hjorth + stats).
- Frequency domain
  - ✓ **Band power** delta/theta/alpha/beta/gamma — absolute and **relative**.
  - ✓ **Band-power ratios** — theta/beta (attention), and the engagement index
    β/(α+θ).
  - ✓ **Spectral entropy** — flatness/complexity of the spectrum.
  - ✓ **Aperiodic 1/f slope + offset** — log-log fit of the PSD (FOOOF-style),
    separating background from oscillatory power.
  - ✓ **High-resolution spectrum** — full EEG spectrum in ~128 bins (the FFT
    processor), per channel, for a spectrogram-style heatmap.
- Time-frequency
  - ✓ **Hilbert band envelope** — analytic-signal amplitude per band; the
    principled smooth band amplitude (vs. the raw oscillation).
  - ✓ Short-time Fourier (visual parity oscillators) — `short_fourier`.
  - Wavelet (Morlet CWT / DWT) — richer time-frequency, deferred.
- Connectivity (multi-channel; needs a matrix view — documented, deferred)
  - Magnitude-squared coherence, Phase Locking Value (PLV), (weighted) Phase Lag
    Index, Granger causality.
- Complexity / nonlinear (deferred)
  - Sample/permutation entropy, Higuchi/Katz fractal dimension, Lempel-Ziv, DFA.

Frame transport: per-channel scalar features are carried in a generic
`features: dict[str, list[float]]` map (one entry per feature, indexed by
channel), so adding a feature never changes the payload contract — the browser
renders the map as a feature×channel heatmap pane. Band power stays in `bands`
and the high-resolution spectrum stays in `fft`.

### Server design

Implement `eegvis/server/app.py`:

- Serve frontend static files from the built `web/dist` folder.
- In development, allow using Vite dev server or proxy instructions.
- Expose:
  - `GET /` browser app,
  - `GET /api/status`,
  - `GET /api/config`,
  - `WS /ws/eeg` realtime stream.

Implement `eegvis/server/websocket.py`:

- Track connected browser clients.
- Broadcast latest frame at configured output rate.
- Drop stale frames instead of queueing infinitely.
- Send status payload immediately on connect.
- Send heartbeat/ping or status every few seconds.
- Handle browser disconnects cleanly.

## Frontend implementation details

### Scene

Use Three.js with a single main render loop.

Scene elements:

- Camera orbiting around head/brain.
- Brain mesh from converted `Realistic_Brain.fbx` to `brain.glb`.
- Head mesh from converted `Realistic_White_Female_Head.obj` to `head.glb`.
- Electrode markers positioned by label.
- Electrode indicator geometry that faces outward from the scalp.
- Optional starfield/MilkyWay background reference if assets are portable.
- Overlay or 3D planes for EEG trace and FFT/band textures.

If model conversion is blocked, create a procedural fallback:

- Transparent head ellipsoid.
- Brain-like central mesh or sphere.
- Electrode points on approximate scalp positions.

### Asset conversion

Convert Unity assets into browser assets:

- Prefer `.glb`/`.gltf` for models.
- Use Blender export manually or scripted conversion if reliable.
- Store converted assets under `web/src/assets/models/` or `web/public/models/`.
- Document exact conversion steps in README.
- Preserve attribution/license notes from the original README for Dean Lavery brain models.

### Electrode rendering

Create `web/src/scene/electrodes.ts`.

Responsibilities:

- Load electrode metadata from JSON.
- Create a marker for each known EEG electrode.
- Match incoming channel names to electrode markers.
- Update colour, scale, opacity, emissive intensity, or particle effect from latest processed values.
- Handle missing channels gracefully.
- Display optional labels.
- Provide debug mode to highlight one electrode, matching the old `debugElectrode` idea.

Colour mapping:

- Preserve the red-to-green / gradient-like behaviour from Unity for normalized values.
- Add band-colour modes for alpha/beta/gamma if available.
- Keep colour mapping centralized so presets can switch modes.

### EEG trace display

Create `web/src/scene/eegTraceTexture.ts`.

Recreate the Unity scrolling EEG render texture using browser-native tools:

Option A, preferred for MVP:

- Use an offscreen `<canvas>` as a dynamic texture.
- Each frame, scroll/draw a vertical column or line segment per channel.
- Upload it as `THREE.CanvasTexture`.
- Display on a 3D plane or HUD panel.

Option B, later:

- Use custom shader/material and GPU texture updates.

Requirements:

- Configurable number of displayed channels.
- Channel overlap similar to `eegChannelOverlap`.
- Invert mode similar to `eegDisplayInvert`.
- Show channel labels optionally.

### FFT / band display

Create `web/src/scene/bandTexture.ts`.

Visual modes (electrode-by-X heatmaps in the top HUD panel; toggled by the GUI
"Display" dropdown and keyboard):

1. `bands` — electrode × 5 bands (delta…gamma) matrix, from `bands`.
2. `fft` — electrode × 128-bin high-resolution spectrum, from `fft` (with a Hz
   axis). Keyboard `C`.
3. `features` — electrode × generic feature matrix from the `features` map
   (Hjorth, line length, spectral entropy, 1/f slope, band ratios, envelopes…),
   each column min/max-normalised across channels. Keyboard `V`.

Plus the time-series strips: `trace` (processed/band, `Z`) and `rawtrace`
(raw, `X`).

Required data source:

- Use `bands` for stable band-power display.
- Use `fft` for the spectrum; the processor delivers a fixed 128 bins.
- Use `features` for scalar per-channel features (extensible — any new key
  appears as a new column automatically).

### Controls and presets

Recreate the spirit of `Controls.cs` with browser controls.

Keyboard defaults:

- `Space`: toggle electrode indicators.
- `Z`: show EEG strip display.
- `X`: show electrode/band display.
- `C`: show FFT display.
- `1`–`7`: switch visual presets.
- Arrow up/down: adjust head cutaway/cutoff or equivalent transparency/cut plane.

GUI controls:

- Connection status.
- Stream name and sample rate.
- Selected visual mode.
- Band selection.
- Electrode label toggle.
- Head opacity/cutaway.
- EEG trace invert.
- Debug electrode selector.
- Processor output toggles if backend exposes them.

Visual presets:

1. Head + brain + raw electrode colours.
2. Head transparent/cutaway + electrodes.
3. Brain-only with electrode energy glow.
4. EEG trace panel emphasis.
5. Short Fourier three-band colour mode.
6. FFT/band matrix mode.
7. Installation/cinematic mode with automatic camera motion.

## Implementation phases for Claude

### Phase 0 — Audit and reference extraction

- Inspect all existing files listed in “Existing project reference points”.
- Extract CGX electrode labels and positions into a Python data file and a frontend JSON file.
- Identify which channels are EEG vs aux/misc/stim for 27-channel and 37-channel CGX streams.
- Identify original visual modes and controls from Unity scripts.
- Add this `PLAN.md` to the repo root.

Deliverables:

- `eegvis/assets/electrodes_cgx.py`
- `web/src/assets/electrodes_cgx.json`
- Notes in README about what was ported from Unity.

### Phase 1 — Backend scaffold

- Create `pyproject.toml`.
- Create `eegvis/` package structure.
- Add CLI command `python -m eegvis run`.
- Add synthetic stream mode.
- Add FastAPI app with `/api/status`, `/api/config`, and `/ws/eeg`.
- Add browser auto-open.
- Add basic tests for startup/config/payload models.

Acceptance criteria:

- `python -m eegvis run --synthetic` starts a local server.
- Browser opens automatically unless `--no-browser` is passed.
- `/api/status` returns JSON.
- `/ws/eeg` emits synthetic `eeg_frame` messages.

### Phase 2 — LSL receiver

- Implement LSL stream discovery.
- Implement stream listing CLI.
- Implement `StreamInlet` chunk receiver.
- Add stream metadata extraction.
- Add reconnection/status handling.
- Add synthetic fallback only when explicitly requested or configured.

Acceptance criteria:

- `python -m eegvis list-streams` prints available LSL streams.
- `python -m eegvis run --stream-type EEG` connects to an EEG stream if available.
- If no stream is found, the app reports this clearly and does not crash.

### Phase 3 — Processing pipeline and plugins

- Implement processor base interface and registry.
- Implement normalization processor.
- Implement bandpass processor.
- Implement FFT processor.
- Implement band power processor.
- Implement smoothing processor.
- Implement visual short-Fourier processor for parity with Unity.
- Add config-driven pipeline.
- Add unit tests with synthetic sine waves.

Acceptance criteria:

- A known 10 Hz synthetic signal produces strong alpha output.
- A known 20 Hz synthetic signal produces strong beta output.
- Processors can be reordered/enabled/disabled in config.
- New processors can be added without editing the LSL receiver or WebSocket code.

### Phase 4 — Frontend scaffold

- Create Vite + TypeScript app in `web/`.
- Add Three.js scene, camera, renderer, orbit controls.
- Add WebSocket client.
- Add protocol types matching backend payloads.
- Show connection status and latest frame index.
- Render placeholder head/brain/electrodes from metadata.

Acceptance criteria:

- Opening the local app shows a 3D scene.
- The scene updates from synthetic WebSocket data.
- Disconnect/reconnect status is visible.

### Phase 5 — Browser visual parity

- Convert/import brain and head models as `.glb`.
- Implement electrode markers using CGX positions.
- Implement red/green or gradient colour mode.
- Implement EEG trace canvas texture.
- Implement band/FFT display panel.
- Implement keyboard controls and GUI controls.
- Implement visual presets 1–7.

Acceptance criteria:

- The browser app resembles the original Unity visualisation.
- Electrode colours update in realtime.
- EEG trace scrolls in realtime.
- FFT/band display updates in realtime.
- `Space`, `Z`, `X`, `C`, and `1`–`7` work.

### Phase 6 — Performance and robustness

- Cap WebSocket send rate, for example 30 Hz by default.
- Drop stale frames rather than buffering indefinitely.
- Keep LSL receiving independent from render/send rate.
- Measure frontend FPS and backend processing time.
- Add low/high data-rate options.
- Consider msgpack only if JSON payloads are too large.
- Add cleanup/shutdown handling.

Acceptance criteria:

- Synthetic mode runs smoothly for at least 10 minutes.
- Real LSL stream runs without unbounded memory growth.
- Browser remains responsive if FFT output is disabled/enabled.

### Phase 7 — Documentation and handoff

- Update `README.md` with:
  - install instructions,
  - how to run synthetic mode,
  - how to connect to real LSL EEG,
  - how to build frontend,
  - how to add a processor,
  - troubleshooting LSL/liblsl issues,
  - asset conversion notes,
  - original Unity visual reference notes.
- Add screenshots or GIFs if possible.
- Keep old Unity instructions under a “Legacy Unity version” section.

Acceptance criteria:

- A new developer can run synthetic mode from a fresh clone.
- A new developer can add a processor by copying a template.
- A user can run the local browser visualisation without opening Unity.

## Testing strategy

### Backend tests

Use `pytest`.

Required tests:

- Config loading.
- Payload serialization.
- Synthetic stream generation.
- Normalization range behaviour.
- Bandpass filter shape and stability.
- FFT peak detection for known sine frequencies.
- Band power detects alpha/beta/gamma synthetic inputs.
- Processor registry loads configured processors.
- WebSocket endpoint emits frames in synthetic mode.

### Frontend tests

Use lightweight tests first.

Required tests:

- Protocol parser accepts backend payload examples.
- Electrode label matching works with missing channels.
- Preset switching updates app state.

Manual visual tests:

- Synthetic 10 Hz alpha-dominant mode visibly activates alpha display.
- Debug electrode mode isolates one electrode.
- Invert mode changes trace display.
- Browser reconnects after backend restart.

## Development order constraints

Implement in this order:

1. Synthetic backend + WebSocket.
2. Minimal browser scene consuming synthetic frames.
3. Processor pipeline using synthetic data.
4. Real LSL receiver.
5. Visual parity features.
6. Performance and polish.

Reason: this avoids blocking frontend work on the physical EEG headset or LSL setup.

## Definition of Done

The rewrite is complete when:

- `python -m eegvis run` starts the local app.
- Python opens the browser automatically.
- Python connects to an LSL EEG stream or runs in synthetic mode.
- Python processes data through configurable processors.
- Browser receives processed data over WebSocket.
- Browser renders a realtime 3D head/brain/electrode visualisation.
- Browser includes EEG trace and FFT/band displays.
- Processor plugins are documented and tested.
- Original Unity project is no longer required for runtime visualisation.
- README explains setup, usage, troubleshooting, and extension points.

## Notes for Claude while coding

- Work incrementally and keep the app runnable after each phase.
- Prefer clear typed interfaces over clever abstractions.
- Preserve visual parity with Unity, but do not recreate Unity-specific render texture architecture unless it makes sense in the browser.
- Keep scientific processing and visual normalization separate.
- Keep realtime loops decoupled: LSL sampling, processing, WebSocket broadcast, and browser rendering should not block each other.
- Use synthetic data heavily for tests and frontend development.
- Add comments where behaviour intentionally mirrors the old Unity code.
- When uncertain, build the simplest visible version first, then improve.
