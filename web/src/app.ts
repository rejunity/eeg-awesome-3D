import { Clock } from "three";
import { createScene, type SceneContext } from "./scene/createScene";
import { BrainHead } from "./scene/brainHead";
import { Electrodes, type ElectrodeShape } from "./scene/electrodes";
import { EEGTraceTexture } from "./scene/eegTraceTexture";
import { BandTexture } from "./scene/bandTexture";
import { RunningStats } from "./scene/runningStats";
import { PRESETS } from "./scene/presets";
import { EEGSocket } from "./net/websocket";
import type {
  EEGFramePayload,
  ElectrodeResponse,
  StatusPayload,
} from "./net/protocol";

export type DisplayMode = "none" | "trace" | "bands" | "fft";

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
  trace = new EEGTraceTexture();
  bands = new BandTexture();
  // 2D HUD overlay (top quarter of the screen) for the trace/band/FFT panels.
  private displayOverlay!: HTMLDivElement;

  private socket = new EEGSocket();
  private clock = new Clock();
  private tickHandlers: Array<(dt: number) => void> = [];
  private electrodesReadyHandlers: Array<(names: string[]) => void> = [];
  private latestFrame: EEGFramePayload | null = null;
  private autoRotate = false;
  private displayMode: DisplayMode = "none";

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

  // Per-channel running mean/SD for colour mapping, and the SD span the colour
  // gradient covers (-colorSD..+colorSD standard deviations).
  private stats = new RunningStats();
  readonly colorSDDefault = 2.5;
  private colorSD = this.colorSDDefault;
  // Band processor applied on the backend to raw data ("none" = pass-through).
  readonly bandDefault = "none";
  private band = this.bandDefault;

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

    for (const canvas of [this.trace.domElement, this.bands.domElement]) {
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
    this.applyPreset(0);
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
    this.socket.onFrame = (f) => this.handleFrame(f);
    this.socket.onClose = () => this.setStatusText("disconnected — reconnecting…", false);
    // Sync the band selection to the backend on (re)connect.
    this.socket.onOpen = () => this._sendBand();
    this.socket.connect();
  }

  private _sendBand(): void {
    this.socket.send({ type: "set_band", band: this.band === "none" ? null : this.band });
  }

  /** Select the backend band processor applied to raw data ("none" = off). */
  setBand(band: string): void {
    this.band = band;
    this.stats = new RunningStats(); // re-baseline; the signal changed
    this._sendBand();
    if (this.guiState) this.guiState.band = band;
  }

  private handleStatus(s: StatusPayload): void {
    const text = `${s.mode}${s.message ? " — " + s.message : ""}`;
    this.setStatusText(text, s.connected);
    const meta = document.getElementById("meta");
    if (meta) {
      meta.textContent = s.stream
        ? `${s.stream.name} · ${s.stream.channel_count}ch @ ${s.stream.sample_rate}Hz`
        : "";
    }
  }

  private handleFrame(f: EEGFramePayload): void {
    this.latestFrame = f;
    // No backend filtering: map each raw value to a z-score via the per-channel
    // running mean/SD, then scale to [-1, 1] over ±colorSD standard deviations.
    const sd = this.colorSD || 1;
    const display = f.latest.map((x, i) => {
      const z = this.stats.zscore(f.channels[i], x);
      return Math.max(-1, Math.min(1, z / sd));
    });
    if (this.electrodes) {
      this.electrodes.update(f.channels, display);
    }
    this.trace.push(display, f.channels);
    if (this.displayMode === "bands" || this.displayMode === "fft") {
      this.bands.update(f);
    }
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

    const traceCanvas = this.trace.domElement;
    const bandsCanvas = this.bands.domElement;
    if (mode === "none") {
      this.displayOverlay.style.display = "none";
      return;
    }
    if (mode !== "trace") {
      this.bands.setMode(mode === "fft" ? "fft" : "bands");
      if (this.latestFrame) this.bands.update(this.latestFrame);
    }
    traceCanvas.style.display = mode === "trace" ? "block" : "none";
    bandsCanvas.style.display = mode === "trace" ? "none" : "block";
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
