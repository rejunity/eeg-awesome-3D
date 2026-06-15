import { Clock } from "three";
import { createScene, type SceneContext } from "./scene/createScene";
import { BrainHead } from "./scene/brainHead";
import { Electrodes, type ElectrodeShape } from "./scene/electrodes";
import { EEGTraceTexture } from "./scene/eegTraceTexture";
import { BandTexture } from "./scene/bandTexture";
import { RunningStats } from "./scene/runningStats";
import { Resampler } from "./scene/resampler";
import { PRESETS } from "./scene/presets";
import { EEGSocket } from "./net/websocket";
import type {
  EEGFramePayload,
  ElectrodeResponse,
  StatusPayload,
} from "./net/protocol";

export type DisplayMode =
  | "none"
  | "trace"
  | "rawtrace"
  | "bands"
  | "fft"
  | "features";

// Fraction of screen height the 2D panel occupies at the top.
const PANEL_FRACTION = 0.25;

/**
 * Top-level application: owns the scene, the data socket, and the render loop.
 * Frames from the backend drive electrode colours and the trace/band textures;
 * the render loop runs independently of the data rate.
 */
export class App {
  ctx: SceneContext;
  brainHead = new BrainHead();
  electrodes!: Electrodes;
  trace = new EEGTraceTexture(); // processed (post-processor) trace
  rawTrace = new EEGTraceTexture(); // raw (pre-processor) trace
  bands = new BandTexture();
  // 2D HUD overlay (top quarter of the screen) for the trace/band/FFT panels.
  private displayOverlay!: HTMLDivElement;
  // Separate running stats so the raw trace is normalised independently.
  private rawStats = new RunningStats();

  private socket = new EEGSocket();
  private clock = new Clock();
  private tickHandlers: Array<(dt: number) => void> = [];
  private electrodesReadyHandlers: Array<(names: string[]) => void> = [];
  private latestFrame: EEGFramePayload | null = null;
  private autoRotate = false;
  private displayMode: DisplayMode = "trace";

  // Frames received but not yet rendered; the render loop drains them so it can
  // skip stale frames for the 3D view when behind.
  private pendingFrames: EEGFramePayload[] = [];
  // HUD: stream info text + received-frame rate (windowed count, Hz).
  private streamInfoText = "";
  private recvRate = 0;
  private recvCount = 0;
  private recvWindowStart = 0;

  // Electrode-array placement params. pitch/height orient the nominal shell
  // (height in the array's local, pitched frame); distance is the gap from the
  // scalp; shape selects sphere/cone. Changing any of these re-projects the
  // electrodes onto the head surface. These defaults also seed the GUI.
  readonly electrodeDefaults = {
    pitch: -0.1,
    height: -0.45,
    distance: 0.04,
    shape: "sphere" as ElectrodeShape,
    // false = head is NOT lit by the electrode point lights (brain still is).
    headLit: false,
  };
  private electrodePitch = this.electrodeDefaults.pitch;
  private electrodeHeight = this.electrodeDefaults.height;
  private electrodeDistance = this.electrodeDefaults.distance;
  private electrodeShape: ElectrodeShape = this.electrodeDefaults.shape;

  // SD span the colour gradient covers (-colorSD..+colorSD standard deviations).
  readonly colorSDDefault = 2.5;
  private colorSD = this.colorSDDefault;
  // The band selector drives the GLOBAL bandpass (none = off, custom = use the
  // low/high controls). Standard EEG band edges (Hz):
  static readonly BAND_RANGES: Record<string, [number, number]> = {
    delta: [1, 4],
    theta: [4, 8],
    alpha: [8, 13],
    beta: [13, 30],
    gamma: [30, 45],
  };
  readonly bandDefault = "none";
  // How often the feature extractors recompute on the backend.
  readonly bandRunDefaults = { mode: "realtime", hz: 30 };
  private bandRunMode = this.bandRunDefaults.mode;
  private bandRunHz = this.bandRunDefaults.hz;

  // Global filter front-end (feeds the trace, electrodes AND extractors).
  readonly filterDefaults = {
    bandpassOn: false,
    bandpassLow: 1,
    bandpassHigh: 45,
    notchOn: false,
    notchHz: 50,
    fftSource: "filtered",
  };
  private filters = { ...this.filterDefaults };
  // What the 3D electrodes colour by: "signal" (filtered sample) or a band /
  // feature key looked up in the frame's bands/features maps.
  readonly electrodeSourceDefault = "signal";
  private electrodeSource = this.electrodeSourceDefault;
  private electrodeStats = new RunningStats();

  // Resampler: plays the fixed-rate sample stream back on the render clock.
  private resampler = new Resampler();
  private channels: string[] = [];
  // The filtered (post notch+bandpass) per-sample stream: its own resampler +
  // running stats so the processed trace plays back at the raw-trace speed.
  private filteredResampler = new Resampler();
  private filteredStats = new RunningStats();
  // Per-channel mean-square envelope of the filtered signal (electrode "power").
  private powerEma: number[] | null = null;

  // Set by installGUI so presets can keep GUI widgets in sync.
  guiState: Record<string, unknown> | null = null;

  constructor(container: HTMLElement) {
    this.ctx = createScene(container);
    this.ctx.scene.add(this.brainHead.group);
    this._buildDisplayOverlay(container);
  }

  /**
   * Build the 2D display overlay: a top-quarter-of-screen HUD that shows the
   * trace / band / FFT canvases on top of the 3D scene (not a 3D plane).
   */
  private _buildDisplayOverlay(container: HTMLElement): void {
    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
      position: "fixed",
      top: "0",
      left: "0",
      width: "100vw",
      height: "25vh",
      zIndex: "5", // above the canvas, below the HUD text / GUI
      pointerEvents: "none",
      overflow: "hidden",
      display: "none",
      borderBottom: "1px solid rgba(255,255,255,0.12)",
      background: "rgba(5,7,13,0.35)",
    } as CSSStyleDeclaration);

    const canvases = [
      this.trace.domElement,
      this.rawTrace.domElement,
      this.bands.domElement,
    ];
    for (const canvas of canvases) {
      Object.assign(canvas.style, {
        position: "absolute",
        inset: "0",
        width: "100%",
        height: "100%",
        display: "none",
      } as CSSStyleDeclaration);
      overlay.appendChild(canvas);
    }

    container.appendChild(overlay);
    this.displayOverlay = overlay;
  }

  async start(): Promise<void> {
    await this.loadElectrodes();
    this.connect();
    this.applyPreset(0); // base scene (head/brain/cutaway); display overridden below
    this.setDisplay("trace");
    this.renderLoop();
  }

  private async loadElectrodes(): Promise<void> {
    const res = await fetch("/api/electrodes");
    const data: ElectrodeResponse = await res.json();
    this.electrodes = new Electrodes(data.electrodes);
    this.electrodes.setShape(this.electrodeShape);
    this.setHeadLitByElectrodes(this.electrodeDefaults.headLit);
    this.ctx.scene.add(this.electrodes.group);
    // Project electrodes onto the head surface once the head model is ready,
    // and again whenever an electrode control changes (see projectElectrodes).
    this.brainHead.onHeadReady(() => this.projectElectrodes());
    for (const h of this.electrodesReadyHandlers) h(this.electrodes.channelNames);
  }

  private connect(): void {
    this.socket.onStatus = (s) => this.handleStatus(s);
    this.socket.onFrame = (f) => this.enqueueFrame(f);
    this.socket.onClose = () => this.setStatusText("disconnected — reconnecting…", false);
    // Sync the band selection + run cadence to the backend on (re)connect.
    this.socket.onOpen = () => {
      this._sendBandRun();
      this._sendBandpass();
      this._sendNotch();
      this._sendFftSource();
    };
    this.socket.connect();
  }

  private _sendBandRun(): void {
    this.socket.send({ type: "set_band_run", mode: this.bandRunMode, hz: this.bandRunHz });
  }

  private _sendBandpass(): void {
    this.socket.send({
      type: "set_bandpass",
      enabled: this.filters.bandpassOn,
      low_hz: this.filters.bandpassLow,
      high_hz: this.filters.bandpassHigh,
    });
  }

  private _sendNotch(): void {
    this.socket.send({
      type: "set_notch",
      enabled: this.filters.notchOn,
      hz: this.filters.notchHz,
    });
  }

  private _sendFftSource(): void {
    this.socket.send({ type: "set_fft_source", source: this.filters.fftSource });
  }

  /** Enable/retune the global bandpass that feeds the feature extractors. */
  setBandpass(opts: { on?: boolean; low?: number; high?: number }): void {
    if (opts.on !== undefined) this.filters.bandpassOn = opts.on;
    if (opts.low !== undefined) this.filters.bandpassLow = opts.low;
    if (opts.high !== undefined) this.filters.bandpassHigh = opts.high;
    // The filtered signal's scale just changed — re-baseline its colour stats.
    this.filteredStats = new RunningStats();
    if (this.electrodeSource === "signal") this.electrodeStats = new RunningStats();
    this._sendBandpass();
  }

  /** Enable/retune the global notch filter. */
  setNotch(opts: { on?: boolean; hz?: number }): void {
    if (opts.on !== undefined) this.filters.notchOn = opts.on;
    if (opts.hz !== undefined) this.filters.notchHz = opts.hz;
    this._sendNotch();
  }

  /** Switch the FFT spectrum pane between the raw and filtered window. */
  setFftSource(source: string): void {
    this.filters.fftSource = source;
    this._sendFftSource();
  }

  /**
   * Band selector -> the global bandpass. "none" disables it; a named band uses
   * its standard edges; "custom" keeps the current low/high controls.
   */
  setBand(band: string): void {
    if (band === "none") {
      this.setBandpass({ on: false });
    } else if (band === "custom") {
      this.setBandpass({ on: true, low: this.filters.bandpassLow, high: this.filters.bandpassHigh });
    } else {
      const r = App.BAND_RANGES[band];
      if (r) this.setBandpass({ on: true, low: r[0], high: r[1] });
    }
    if (this.guiState) {
      this.guiState.band = band;
      this.guiState.bandpassLow = this.filters.bandpassLow;
      this.guiState.bandpassHigh = this.filters.bandpassHigh;
    }
  }

  /** Set the bandpass edges directly (from the low/high sliders) -> "custom". */
  setBandpassRange(low: number, high: number): void {
    this.setBandpass({ on: true, low, high });
    if (this.guiState) this.guiState.band = "custom";
  }

  /** Current bandpass edges [low, high] in Hz (so the GUI can sync its sliders). */
  get bandpassRange(): [number, number] {
    return [this.filters.bandpassLow, this.filters.bandpassHigh];
  }

  /** Choose what the 3D electrodes colour by ("signal" or a band/feature key). */
  setElectrodeSource(source: string): void {
    this.electrodeSource = source;
    this.electrodeStats = new RunningStats(); // re-baseline; the quantity changed
  }

  /** Set the feature-extractor recompute cadence. */
  setBandRun(mode: string, hz: number): void {
    this.bandRunMode = mode;
    this.bandRunHz = hz;
    this._sendBandRun();
  }

  private handleStatus(s: StatusPayload): void {
    const text = `${s.mode}${s.message ? " — " + s.message : ""}`;
    this.setStatusText(text, s.connected);
    this.streamInfoText = s.stream
      ? `${s.stream.name} · ${s.stream.channel_count}ch @ ${s.stream.sample_rate}Hz`
      : "";
    if (s.stream) {
      this.resampler.setRate(s.stream.sample_rate);
      this.filteredResampler.setRate(s.stream.sample_rate);
    }
    this._renderMeta();
  }

  /** HUD meta line: stream info plus the measured received-frame rate. */
  private _renderMeta(): void {
    const meta = document.getElementById("meta");
    if (!meta) return;
    const rate =
      this.recvRate > 0 ? ` · recv ${this.recvRate.toFixed(1)}Hz` : "";
    meta.textContent = this.streamInfoText + rate;
  }

  /** Cheap per-frame handler: buffer the frame and tally the receive rate. */
  private enqueueFrame(f: EEGFramePayload): void {
    this.pendingFrames.push(f);
    this.recvCount++;
    const now = performance.now();
    if (this.recvWindowStart === 0) this.recvWindowStart = now;
    const elapsed = now - this.recvWindowStart;
    if (elapsed >= 500) {
      this.recvRate = (this.recvCount * 1000) / elapsed;
      this.recvCount = 0;
      this.recvWindowStart = now;
      this._renderMeta();
    }
  }

  /**
   * Called every render frame. Plays the raw and filtered sample streams back on
   * the render clock (bursty arrivals -> steady). The raw stream feeds the raw
   * trace (X); the filtered stream (post notch+bandpass) feeds the processed
   * trace (Z). The electrodes colour by the selected source: the filtered signal
   * ("signal"), or a per-channel band-power / feature value from the frame.
   */
  private consumeFrames(nowMs: number): void {
    const sd = this.colorSD || 1;
    const clampZ = (stats: RunningStats, ch: string, x: number) =>
      Math.max(-1, Math.min(1, stats.zscore(ch, x) / sd));

    // 1) Ingest newly received frames into the raw + filtered resamplers.
    for (const f of this.pendingFrames) {
      this.channels = f.channels;
      this.latestFrame = f;
      this.resampler.push(f.samples);
      this.filteredResampler.push(
        f.filtered_samples.length ? f.filtered_samples : f.samples,
      );
    }
    this.pendingFrames.length = 0;

    // 2) Raw trace (X) at the source rate.
    for (const row of this.resampler.drain(nowMs)) {
      const rawD = row.map((x, i) => clampZ(this.rawStats, this.channels[i], x));
      this.rawTrace.push(rawD, this.channels);
    }

    // 3) Filtered trace (Z) at the source rate. == raw when no filter is on.
    // Also track a per-channel mean-square envelope for the "power" electrode src.
    let lastFiltered: number[] | null = null;
    const a = 0.02; // ~0.2 s power-envelope time constant
    for (const row of this.filteredResampler.drain(nowMs)) {
      const d = row.map((x, i) => clampZ(this.filteredStats, this.channels[i], x));
      this.trace.push(d, this.channels);
      lastFiltered = d;
      if (!this.powerEma || this.powerEma.length !== row.length) {
        this.powerEma = row.map((x) => x * x);
      } else {
        for (let i = 0; i < row.length; i++) {
          this.powerEma[i] = (1 - a) * this.powerEma[i] + a * row[i] * row[i];
        }
      }
    }

    // 4) Electrodes: colour by the selected source.
    const elec = this._electrodeValues(lastFiltered, clampZ);
    if (this.electrodes && elec) this.electrodes.update(this.channels, elec);
    if (
      (this.displayMode === "bands" ||
        this.displayMode === "fft" ||
        this.displayMode === "features") &&
      this.latestFrame
    ) {
      this.bands.update(this.latestFrame);
    }
  }

  /**
   * Per-channel electrode display values for the current source. "signal" uses
   * the just-played filtered sample; otherwise a per-channel band-power/feature
   * from the latest frame, z-scored over time so the colour scale is stable.
   */
  private _electrodeValues(
    lastFiltered: number[] | null,
    clampZ: (s: RunningStats, ch: string, x: number) => number,
  ): number[] | null {
    if (this.electrodeSource === "signal") return lastFiltered;
    if (this.electrodeSource === "power") {
      if (!this.powerEma) return null;
      return this.powerEma.map((p, i) => clampZ(this.electrodeStats, this.channels[i], p));
    }
    const f = this.latestFrame;
    if (!f) return null;
    const vals = f.features[this.electrodeSource] ?? f.bands[this.electrodeSource];
    if (!vals || !vals.length) return null;
    return vals.map((v, i) => clampZ(this.electrodeStats, this.channels[i], v));
  }

  /** SD span the electrode colour gradient covers (±colorSD std deviations). */
  setColorSD(sd: number): void {
    this.colorSD = sd;
  }

  private setStatusText(text: string, connected: boolean): void {
    const status = document.getElementById("status");
    const hud = document.getElementById("hud");
    if (status) status.textContent = text;
    if (hud) hud.classList.toggle("connected", connected);
  }

  // -- display modes -------------------------------------------------------

  setDisplay(mode: DisplayMode): void {
    this.displayMode = mode;
    if (this.guiState) this.guiState.display = mode;

    if (mode === "none") {
      this.displayOverlay.style.display = "none";
      return;
    }
    const matrix = mode === "bands" || mode === "fft" || mode === "features";
    if (matrix) {
      this.bands.setMode(mode as "bands" | "fft" | "features");
      if (this.latestFrame) this.bands.update(this.latestFrame);
    }
    this.trace.domElement.style.display = mode === "trace" ? "block" : "none";
    this.rawTrace.domElement.style.display = mode === "rawtrace" ? "block" : "none";
    this.bands.domElement.style.display = matrix ? "block" : "none";
    this.displayOverlay.style.display = "block";
  }

  /** Toggle a display mode: show it, or close the panel if it's already shown. */
  toggleDisplay(mode: Exclude<DisplayMode, "none">): void {
    this.setDisplay(this.displayMode === mode ? "none" : mode);
  }

  showTrace(): void {
    this.setDisplay("trace");
  }
  showBands(): void {
    this.setDisplay("bands");
  }
  showFFT(): void {
    this.setDisplay("fft");
  }
  showFeatures(): void {
    this.setDisplay("features");
  }

  applyPreset(index: number): void {
    if (index < 0 || index >= PRESETS.length) return;
    PRESETS[index].apply(this);
    if (this.guiState) {
      this.guiState.preset = PRESETS[index].name;
      this.guiState.indicators = true;
      this.guiState.autoRotate = this.autoRotate;
    }
  }

  setAutoRotate(on: boolean): void {
    this.autoRotate = on;
    if (this.guiState) this.guiState.autoRotate = on;
  }

  /** Pitch the electrode array (radians about X, through the brain centre). */
  setElectrodePitch(radians: number): void {
    this.electrodePitch = radians;
    this.projectElectrodes();
  }

  /**
   * Move the electrode array along its own (pitched) up axis, then re-project
   * onto the head — so the electrodes slide up/down the scalp.
   */
  setElectrodeVerticalOffset(dy: number): void {
    this.electrodeHeight = dy;
    this.projectElectrodes();
  }

  /** Gap (world units) between the scalp surface and the electrode marker. */
  setElectrodeDistance(distance: number): void {
    this.electrodeDistance = distance;
    this.projectElectrodes();
  }

  /** Electrode marker shape: sphere, or cone pointing outward along the normal. */
  setElectrodeShape(shape: ElectrodeShape): void {
    this.electrodeShape = shape;
    this.electrodes?.setShape(shape);
    this.projectElectrodes();
  }

  /**
   * Toggle whether the head is lit by the electrode (point) lights. The lights
   * are global, so the brain and markers are always lit; turning this off makes
   * only the head material ignore the point lights.
   */
  setHeadLitByElectrodes(on: boolean): void {
    this.brainHead.setHeadExcludesPointLights(!on);
  }

  /** Raycast every electrode onto the head surface with the current params. */
  private projectElectrodes(): void {
    if (!this.electrodes) return;
    this.electrodes.project(this.brainHead.raycastTarget, {
      pitch: this.electrodePitch,
      height: this.electrodeHeight,
      distance: this.electrodeDistance,
      brainCenter: this.brainHead.brainCenter,
    });
  }

  // -- hooks ---------------------------------------------------------------

  onTick(handler: (dt: number) => void): void {
    this.tickHandlers.push(handler);
  }

  onElectrodesReady(handler: (names: string[]) => void): void {
    if (this.electrodes) handler(this.electrodes.channelNames);
    else this.electrodesReadyHandlers.push(handler);
  }

  // -- render loop ---------------------------------------------------------

  private renderLoop = (): void => {
    requestAnimationFrame(this.renderLoop);
    // Ingest received samples and play them back on the render clock.
    this.consumeFrames(performance.now());
    const dt = this.clock.getDelta();
    for (const h of this.tickHandlers) h(dt);
    if (this.autoRotate) {
      this.ctx.scene.rotation.y += dt * 0.2;
    }
    this.ctx.controls.update();

    // When the 2D panel covers the top quarter, confine the 3D render to the
    // area below it so the head isn't hidden behind the panel.
    const w = window.innerWidth;
    const h = window.innerHeight;
    const viewH = this.displayMode === "none" ? h : h * (1 - PANEL_FRACTION);
    this.ctx.renderer.setViewport(0, 0, w, viewH);
    const aspect = w / viewH;
    if (Math.abs(this.ctx.camera.aspect - aspect) > 1e-4) {
      this.ctx.camera.aspect = aspect;
      this.ctx.camera.updateProjectionMatrix();
    }

    this.ctx.renderer.render(this.ctx.scene, this.ctx.camera);
  };
}
