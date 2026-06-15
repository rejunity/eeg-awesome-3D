import { CanvasTexture, LinearFilter, NearestFilter } from "three";
import { heat } from "./colormap";
import type { EEGFramePayload } from "../net/protocol";

/**
 * Band / FFT / features display panel as a CanvasTexture.
 *
 * Modes:
 *  - "bands":    electrode-by-band matrix (electrodes on Y, the 5 bands on X).
 *  - "fft":      electrode-by-frequency heatmap (high-resolution spectrum).
 *  - "features": electrode-by-feature heatmap of the generic `features` map.
 *
 * Channel names live in a fixed left gutter (never drawn over the heatmap), and
 * the canvas is resized to the pane's pixel size so text isn't stretched.
 */
export type BandMode = "bands" | "fft" | "features";

const BAND_ORDER = ["delta", "theta", "alpha", "beta", "gamma"];
const GUTTER = 54; // left column reserved for channel names (px)
const LABEL_FONT = "10px ui-monospace, monospace";
const AXIS_FONT = "9px ui-monospace, monospace";

// Contrast boost: expand low values so faint spectral detail is visible.
const contrast = (v: number) => Math.pow(Math.max(0, Math.min(1, v)), 0.4);

export class BandTexture {
  readonly texture: CanvasTexture;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private mode: BandMode = "bands";

  constructor(width = 1024, height = 320) {
    this.canvas = document.createElement("canvas");
    this.canvas.width = width;
    this.canvas.height = height;
    this.ctx = this.canvas.getContext("2d")!;
    this.texture = new CanvasTexture(this.canvas);
    this.texture.minFilter = LinearFilter;
    this.texture.magFilter = NearestFilter;
  }

  get domElement(): HTMLCanvasElement {
    return this.canvas;
  }

  setMode(mode: BandMode): void {
    this.mode = mode;
  }

  /** Match the canvas backing-store to its displayed pixel size (no stretch). */
  resize(w: number, h: number): void {
    const cw = Math.max(64, Math.round(w));
    const ch = Math.max(32, Math.round(h));
    if (this.canvas.width !== cw || this.canvas.height !== ch) {
      this.canvas.width = cw;
      this.canvas.height = ch;
    }
  }

  update(frame: EEGFramePayload): void {
    if (this.mode === "fft" && frame.fft) this.drawFFT(frame);
    else if (this.mode === "features") this.drawFeatures(frame);
    else this.drawBands(frame);
    this.texture.needsUpdate = true;
  }

  private clear(): void {
    this.ctx.fillStyle = "#05070d";
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
  }

  private drawBands(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    this.clear();
    const nCh = frame.channels.length;
    if (nCh === 0) return;
    const cellH = height / nCh;
    const cellW = (width - GUTTER) / BAND_ORDER.length;

    for (let b = 0; b < BAND_ORDER.length; b++) {
      const values = frame.bands[BAND_ORDER[b]] ?? [];
      for (let i = 0; i < nCh; i++) {
        ctx.fillStyle = `#${heat(contrast(values[i] ?? 0)).getHexString()}`;
        ctx.fillRect(GUTTER + b * cellW, i * cellH, cellW - 1, cellH - 1);
      }
    }
    this.drawColLabels(BAND_ORDER, cellW);
    this.drawRowLabels(frame.channels, cellH);
  }

  private drawFFT(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    this.clear();
    const fft = frame.fft!;
    const values = fft.values;
    const nCh = values.length;
    if (nCh === 0) return;
    const nBins = values[0].length;
    const plotW = width - GUTTER;
    const cellW = plotW / nBins;
    const cellH = height / nCh;

    let max = 1e-9;
    for (const row of values) for (const v of row) if (v > max) max = v;

    for (let i = 0; i < nCh; i++) {
      for (let f = 0; f < nBins; f++) {
        ctx.fillStyle = `#${heat(contrast((values[i][f] ?? 0) / max)).getHexString()}`;
        ctx.fillRect(GUTTER + f * cellW, i * cellH, Math.max(1, cellW), cellH);
      }
    }
    this.drawRowLabels(frame.channels, cellH);
    this.drawFreqAxis(fft.freqs, GUTTER, plotW);
  }

  private drawFeatures(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    this.clear();
    const keys = Object.keys(frame.features).sort();
    const nCh = frame.channels.length;
    if (keys.length === 0 || nCh === 0) {
      ctx.fillStyle = "#cdd6f4";
      ctx.font = LABEL_FONT;
      ctx.fillText("no features — enable feature processors", GUTTER + 4, 16);
      return;
    }
    const cellW = (width - GUTTER) / keys.length;
    const cellH = height / nCh;

    keys.forEach((key, c) => {
      const vals = frame.features[key] ?? [];
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = 0; i < nCh; i++) {
        const v = vals[i];
        if (v === undefined || !Number.isFinite(v)) continue;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      const span = hi - lo;
      for (let i = 0; i < nCh; i++) {
        const v = vals[i] ?? lo;
        const norm = span > 1e-12 ? (v - lo) / span : 0.5;
        ctx.fillStyle = `#${heat(norm).getHexString()}`;
        ctx.fillRect(GUTTER + c * cellW, i * cellH, cellW - 1, cellH);
      }
    });
    this.drawRotatedColLabels(keys, cellW);
    this.drawRowLabels(frame.channels, cellH);
  }

  private drawColLabels(cols: string[], cellW: number): void {
    const ctx = this.ctx;
    ctx.fillStyle = "#cdd6f4";
    ctx.font = LABEL_FONT;
    cols.forEach((c, i) => ctx.fillText(c, GUTTER + i * cellW + 2, 11));
  }

  private drawRotatedColLabels(cols: string[], cellW: number): void {
    const ctx = this.ctx;
    ctx.fillStyle = "#cdd6f4";
    ctx.font = AXIS_FONT;
    cols.forEach((c, i) => {
      ctx.save();
      ctx.translate(GUTTER + i * cellW + cellW / 2 + 3, 4);
      ctx.rotate(Math.PI / 2);
      ctx.fillText(c, 0, 0);
      ctx.restore();
    });
  }

  /** Channel names in the left gutter; skipped/stepped when rows are tiny. */
  private drawRowLabels(rows: string[], cellH: number): void {
    const ctx = this.ctx;
    ctx.fillStyle = "#cdd6f4";
    ctx.font = LABEL_FONT;
    ctx.textBaseline = "middle";
    const step = Math.max(1, Math.ceil(11 / cellH)); // avoid vertical overlap
    for (let i = 0; i < rows.length; i++) {
      if (i % step !== 0) continue;
      ctx.fillText(rows[i].slice(0, 7), 2, i * cellH + cellH / 2);
    }
    ctx.textBaseline = "alphabetic";
  }

  private drawFreqAxis(freqs: number[], x0: number, plotW: number): void {
    if (freqs.length === 0) return;
    const ctx = this.ctx;
    ctx.fillStyle = "#9aa6c4";
    ctx.font = AXIS_FONT;
    const fmax = freqs[freqs.length - 1];
    const ticks = 8;
    for (let t = 0; t <= ticks; t++) {
      const x = x0 + (t / ticks) * plotW;
      const hz = Math.round((t / ticks) * fmax);
      ctx.fillText(`${hz}`, Math.min(x + 1, x0 + plotW - 14), this.canvas.height - 2);
    }
  }
}
