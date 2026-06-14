import { CanvasTexture, LinearFilter, NearestFilter } from "three";
import { heat } from "./colormap";
import type { EEGFramePayload } from "../net/protocol";

/**
 * Band / FFT / features display panel as a CanvasTexture.
 *
 * Modes:
 *  - "bands":    electrode-by-band matrix (electrodes on Y, the 5 bands on X).
 *  - "fft":      electrode-by-frequency heatmap (high-resolution spectrum).
 *  - "features": electrode-by-feature heatmap of the generic `features` map
 *                (Hjorth, line length, entropy, 1/f slope, ratios, envelopes…),
 *                each column min/max-normalised across channels.
 */
export type BandMode = "bands" | "fft" | "features";

const BAND_ORDER = ["delta", "theta", "alpha", "beta", "gamma"];

export class BandTexture {
  readonly texture: CanvasTexture;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private mode: BandMode = "bands";

  constructor(width = 768, height = 512) {
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
    const cellW = width / BAND_ORDER.length;

    for (let b = 0; b < BAND_ORDER.length; b++) {
      const values = frame.bands[BAND_ORDER[b]] ?? [];
      for (let i = 0; i < nCh; i++) {
        const v = values[i] ?? 0;
        ctx.fillStyle = `#${heat(v).getHexString()}`;
        ctx.fillRect(b * cellW, i * cellH, cellW - 1, cellH - 1);
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
    this.drawRowLabels(frame.channels, cellH);
    this.drawFreqAxis(fft.freqs, width);
  }

  private drawFeatures(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    this.clear();

    const keys = Object.keys(frame.features).sort();
    const nCh = frame.channels.length;
    if (keys.length === 0 || nCh === 0) {
      ctx.fillStyle = "#cdd6f4";
      ctx.font = "13px ui-monospace, monospace";
      ctx.fillText("no features — enable feature processors", 8, 20);
      return;
    }
    const cellW = width / keys.length;
    const cellH = height / nCh;

    keys.forEach((key, c) => {
      const vals = frame.features[key] ?? [];
      // Min/max-normalise this feature across channels so its column spans 0..1.
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
        ctx.fillRect(c * cellW, i * cellH, cellW - 1, cellH - 1);
      }
    });
    this.drawRotatedColLabels(keys, cellW);
    this.drawRowLabels(frame.channels, cellH);
  }

  private drawColLabels(cols: string[], cellW: number): void {
    const ctx = this.ctx;
    ctx.fillStyle = "#cdd6f4";
    ctx.font = "11px ui-monospace, monospace";
    cols.forEach((c, i) => ctx.fillText(c, i * cellW + 2, 12));
  }

  private drawRotatedColLabels(cols: string[], cellW: number): void {
    const ctx = this.ctx;
    ctx.fillStyle = "#cdd6f4";
    ctx.font = "10px ui-monospace, monospace";
    cols.forEach((c, i) => {
      ctx.save();
      ctx.translate(i * cellW + cellW / 2 + 3, 6);
      ctx.rotate(Math.PI / 2);
      ctx.fillText(c, 0, 0);
      ctx.restore();
    });
  }

  private drawRowLabels(rows: string[], cellH: number): void {
    if (cellH < 10) return;
    const ctx = this.ctx;
    ctx.fillStyle = "#cdd6f4";
    ctx.font = "11px ui-monospace, monospace";
    rows.forEach((r, i) => ctx.fillText(r, 2, i * cellH + cellH - 2));
  }

  private drawFreqAxis(freqs: number[], width: number): void {
    if (freqs.length === 0) return;
    const ctx = this.ctx;
    ctx.fillStyle = "#9aa6c4";
    ctx.font = "10px ui-monospace, monospace";
    const fmax = freqs[freqs.length - 1];
    const ticks = 8;
    for (let t = 0; t <= ticks; t++) {
      const x = (t / ticks) * width;
      const hz = Math.round((t / ticks) * fmax);
      ctx.fillText(`${hz}`, Math.min(x + 1, width - 16), this.canvas.height - 2);
    }
  }
}
