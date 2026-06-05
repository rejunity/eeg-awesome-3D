import { Clock } from "three";
import { createScene, type SceneContext } from "./scene/createScene";
import { BrainHead } from "./scene/brainHead";
import { Electrodes, type ElectrodeShape } from "./scene/electrodes";
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
  };
  private electrodePitch = this.electrodeDefaults.pitch;
  private electrodeHeight = this.electrodeDefaults.height;
  private electrodeDistance = this.electrodeDefaults.distance;
  private electrodeShape: ElectrodeShape = this.electrodeDefaults.shape;

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
    this.electrodes.setShape(this.electrodeShape);
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
    this.ctx.renderer.render(this.ctx.scene, this.ctx.camera);
  };
}
