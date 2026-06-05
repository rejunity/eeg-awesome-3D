import { Clock, Group, Vector3 } from "three";
import { createScene, type SceneContext } from "./scene/createScene";
import { BrainHead } from "./scene/brainHead";
import { Electrodes } from "./scene/electrodes";
import { EEGTraceTexture } from "./scene/eegTraceTexture";
import { BandTexture } from "./scene/bandTexture";
import { DisplayPanel } from "./scene/displayPanel";
import { PRESETS } from "./scene/presets";
import { EEGSocket } from "./net/websocket";
import type {
  EEGFramePayload,
  ElectrodeResponse,
  StatusPayload,
} from "./net/protocol";

export type DisplayMode = "none" | "trace" | "bands" | "fft";

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
  panel = new DisplayPanel();

  // Pivot for the electrode array, placed at the brain centre so the whole
  // array can be pitched around it (see setElectrodePitch). The vertical
  // offset rides this pivot's local (pitched) frame (setElectrodeVerticalOffset).
  private electrodePivot = new Group();
  private electrodeBaseCenter = new Vector3();
  private socket = new EEGSocket();
  private clock = new Clock();
  private tickHandlers: Array<(dt: number) => void> = [];
  private electrodesReadyHandlers: Array<(names: string[]) => void> = [];
  private latestFrame: EEGFramePayload | null = null;
  private autoRotate = false;
  private displayMode: DisplayMode = "none";

  // Set by installGUI so presets can keep GUI widgets in sync.
  guiState: Record<string, unknown> | null = null;

  constructor(container: HTMLElement) {
    this.ctx = createScene(container);
    this.ctx.scene.add(this.brainHead.group);
    this.ctx.scene.add(this.panel.mesh);
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
    // Mount the array under a pivot at the brain centre and offset it by the
    // same amount, so the electrodes keep their world positions but rotating
    // the pivot spins the whole array around the brain centre.
    const center = this.brainHead.brainCenter;
    this.electrodeBaseCenter.copy(center);
    this.electrodePivot.position.copy(center);
    this.electrodes.group.position.copy(center.clone().negate());
    this.electrodePivot.add(this.electrodes.group);
    this.ctx.scene.add(this.electrodePivot);
    for (const h of this.electrodesReadyHandlers) h(this.electrodes.channelNames);
  }

  private connect(): void {
    this.socket.onStatus = (s) => this.handleStatus(s);
    this.socket.onFrame = (f) => this.handleFrame(f);
    this.socket.onClose = () => this.setStatusText("disconnected — reconnecting…", false);
    this.socket.connect();
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
    if (this.electrodes) {
      this.electrodes.update(f.channels, f.normalized, f.bands);
    }
    this.trace.push(f.normalized);
    if (this.displayMode === "bands" || this.displayMode === "fft") {
      this.bands.update(f);
    }
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
      this.panel.setVisible(false);
      return;
    }
    if (mode === "trace") {
      this.panel.setTexture(this.trace.texture);
    } else {
      this.bands.setMode(mode === "fft" ? "fft" : "bands");
      this.panel.setTexture(this.bands.texture);
      if (this.latestFrame) this.bands.update(this.latestFrame);
    }
    this.panel.setVisible(true);
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

  /** Pitch the whole electrode array (radians) about its pivot. */
  setElectrodePitch(radians: number): void {
    this.electrodePivot.rotation.x = radians;
  }

  /**
   * Move the electrode array vertically in the pivot's LOCAL frame, i.e. along
   * the array's own up axis (which tilts with the electrode pitch), not world
   * Y. Applied to the array inside the pivot so the offset rides the rotation;
   * the pivot itself stays the fixed rotation origin.
   */
  setElectrodeVerticalOffset(dy: number): void {
    this.electrodes.group.position.y = -this.electrodeBaseCenter.y + dy;
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
    this.ctx.renderer.render(this.ctx.scene, this.ctx.camera);
  };
}
