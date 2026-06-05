import { CanvasTexture, LinearFilter, NearestFilter } from "three";
import { heat } from "./colormap";
import type { EEGFramePayload } from "../net/protocol";

/**
 * Band / FFT display panel as a CanvasTexture.
 *
 * Two modes (PLAN.md FFT/band display):
 *  - "bands": electrode-by-band matrix (electrodes on Y, the 5 bands on X).
 *  - "fft":   electrode-by-frequency matrix from the fft block when available.
 */
export type BandMode = "bands" | "fft";

const BAND_ORDER = ["delta", "theta", "alpha", "beta", "gamma"];

export class BandTexture {
  readonly texture: CanvasTexture;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private mode: BandMode = "bands";

  constructor(width = 512, height = 512) {
    this.canvas = document.createElement("canvas");
    this.canvas.width = width;
    this.canvas.height = height;
    this.ctx = this.canvas.getContext("2d")!;
    this.ctx.fillStyle = "#05070d";
    this.ctx.fillRect(0, 0, width, height);
    this.texture = new CanvasTexture(this.canvas);
    this.texture.minFilter = LinearFilter;
    this.texture.magFilter = NearestFilter;
  }

  /** The backing canvas, for displaying the panel as a 2D DOM overlay. */
  get domElement(): HTMLCanvasElement {
    return this.canvas;
  }

  setMode(mode: BandMode): void {
    this.mode = mode;
  }

  update(frame: EEGFramePayload): void {
    if (this.mode === "fft" && frame.fft) this.drawFFT(frame);
    else this.drawBands(frame);
    this.texture.needsUpdate = true;
  }

  private drawBands(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    ctx.fillStyle = "#05070d";
    ctx.fillRect(0, 0, width, height);

    const nCh = frame.channels.length;
    if (nCh === 0) return;
    const cellH = height / nCh;
    const cellW = width / BAND_ORDER.length;

    for (let b = 0; b < BAND_ORDER.length; b++) {
      const values = frame.bands[BAND_ORDER[b]] ?? [];
      for (let i = 0; i < nCh; i++) {
        const v = values[i] ?? 0;
        ctx.fillStyle = `#${heat(v).getHexString()}`;
        ctx.fillRect(b * cellW, i * cellH, cellW - 1, cellH - 1);
      }
    }
    this.drawLabels(BAND_ORDER, frame.channels, cellW, cellH);
  }

  private drawFFT(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    ctx.fillStyle = "#05070d";
    ctx.fillRect(0, 0, width, height);

    const values = frame.fft!.values;
    const nCh = values.length;
    if (nCh === 0) return;
    const nBins = values[0].length;
    const cellW = width / nBins;
    const cellH = height / nCh;

    // Normalize against the panel max for visibility.
    let max = 1e-9;
    for (const row of values) for (const v of row) if (v > max) max = v;

    for (let i = 0; i < nCh; i++) {
      for (let f = 0; f < nBins; f++) {
        const v = (values[i][f] ?? 0) / max;
        ctx.fillStyle = `#${heat(v).getHexString()}`;
        ctx.fillRect(f * cellW, i * cellH, Math.max(1, cellW), cellH - 1);
      }
    }
  }

  private drawLabels(
    cols: string[],
    rows: string[],
    cellW: number,
    cellH: number,
  ): void {
    const ctx = this.ctx;
    ctx.fillStyle = "#cdd6f4";
    ctx.font = "11px ui-monospace, monospace";
    cols.forEach((c, i) => ctx.fillText(c, i * cellW + 2, 12));
    if (cellH >= 10) {
      rows.forEach((r, i) => ctx.fillText(r, 2, i * cellH + cellH - 2));
    }
  }
}
