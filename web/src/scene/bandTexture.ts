import { CanvasTexture, LinearFilter, NearestFilter } from "three";
import { diverging, heat } from "./colormap";
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
export type BandMode = "bands" | "fft" | "features" | "asymmetry";

const BAND_ORDER = ["delta", "theta", "alpha", "beta", "gamma"];
const GUTTER = 54; // left column reserved for channel names (px)
const LABEL_FONT = "10px ui-monospace, monospace";
const AXIS_FONT = "9px ui-monospace, monospace";

export class BandTexture {
  readonly texture: CanvasTexture;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private mode: BandMode = "bands";
  // Heatmap contrast gamma: <1 expands low values (more contrast). Adjustable.
  private gamma = 0.4;
  // Black point: normalized energy below this maps to 0 (true black), so the
  // noise floor / out-of-band bins don't show as a constant bias colour.
  private blackPoint = 0.04;
  // Optional channel-row ordering (from the electrode-sort mode); null = stream
  // order. Only the per-electrode FFT panel honours it.
  private channelOrder: number[] | null = null;

  // Subtract the black point, rescale, then gamma-expand the remainder.
  private contrast(v: number): number {
    const x = Math.max(0, Math.min(1, v));
    if (x <= this.blackPoint) return 0;
    return Math.pow((x - this.blackPoint) / (1 - this.blackPoint), this.gamma);
  }

  /** Set the heatmap contrast (amount in [0,1]; higher = more contrast). */
  setContrast(amount: number): void {
    this.gamma = Math.max(0.15, Math.min(1, 1 - amount * 0.85));
  }

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

  /** Row order for the FFT panel (indices into the frame's channels); null = as-is. */
  setChannelOrder(order: number[] | null): void {
    this.channelOrder = order;
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
    else if (this.mode === "asymmetry") this.drawAsymmetry(frame);
    else this.drawBands(frame);
    this.texture.needsUpdate = true;
  }

  private clear(): void {
    this.ctx.fillStyle = "#05070d";
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
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

    // Row order: apply the electrode-sort permutation, keeping only valid rows.
    const rows = (this.channelOrder ?? values.map((_, i) => i)).filter(
      (k) => k >= 0 && k < nCh,
    );
    const labels = rows.map((k) => frame.channels[k] ?? String(k));

    let max = 1e-9;
    for (const row of values) for (const v of row) if (v > max) max = v;

    for (let i = 0; i < rows.length; i++) {
      const src = values[rows[i]];
      for (let f = 0; f < nBins; f++) {
        ctx.fillStyle = `#${heat(this.contrast((src[f] ?? 0) / max)).getHexString()}`;
        ctx.fillRect(GUTTER + f * cellW, i * cellH, Math.max(1, cellW), cellH);
      }
    }
    this.drawRowLabels(labels, cellH);
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

  // "bands" pane: per-lobe band power (region x band heatmap, FFT colour ramp).
  private drawBands(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    this.clear();
    const rp = frame.region_power;
    if (!rp || rp.regions.length === 0) {
      ctx.fillStyle = "#cdd6f4";
      ctx.font = LABEL_FONT;
      ctx.fillText("no lobe power — enable the region_power processor", GUTTER + 4, 16);
      return;
    }
    const regions = rp.regions; // rows
    const cellH = height / regions.length;
    const cellW = (width - GUTTER) / BAND_ORDER.length;

    // Normalise to the panel max, then the same heat ramp + contrast as the FFT.
    let max = 1e-12;
    for (const b of BAND_ORDER) {
      for (const v of rp.bands[b] ?? []) if (v > max) max = v;
    }
    for (let c = 0; c < BAND_ORDER.length; c++) {
      const vals = rp.bands[BAND_ORDER[c]] ?? [];
      for (let r = 0; r < regions.length; r++) {
        ctx.fillStyle = `#${heat(this.contrast((vals[r] ?? 0) / max)).getHexString()}`;
        ctx.fillRect(GUTTER + c * cellW, r * cellH, cellW - 1, cellH - 1);
      }
    }
    this.drawColLabels(BAND_ORDER, cellW);
    this.drawRowLabels(regions, cellH);
  }

  private drawAsymmetry(frame: EEGFramePayload): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    this.clear();
    const asym = frame.asymmetry;
    if (!asym || asym.regions.length === 0) {
      ctx.fillStyle = "#cdd6f4";
      ctx.font = LABEL_FONT;
      ctx.fillText("no asymmetry — enable the asymmetry processor", GUTTER + 4, 16);
      return;
    }
    const regions = asym.regions; // rows
    const cellH = height / regions.length;
    const cellW = (width - GUTTER) / BAND_ORDER.length;
    // (R-L)/(R+L) magnitude that fills the bar to the cell edge.
    const FULL_SCALE = 0.3;
    const warm = `#${diverging(1).getHexString()}`; // right-dominant
    const cool = `#${diverging(-1).getHexString()}`; // left-dominant

    for (let c = 0; c < BAND_ORDER.length; c++) {
      const vals = asym.bands[BAND_ORDER[c]] ?? [];
      for (let r = 0; r < regions.length; r++) {
        const x0 = GUTTER + c * cellW;
        const y0 = r * cellH;
        // Cell background + faint frame.
        ctx.fillStyle = "#0d1119";
        ctx.fillRect(x0, y0, cellW - 1, cellH - 1);

        const midX = x0 + cellW / 2;
        const midY = y0 + cellH / 2;
        const halfW = ((cellW - 2) / 2) * 0.9;
        const barH = Math.max(3, cellH * 0.42);

        // Centre ("balanced") reference line.
        ctx.strokeStyle = "rgba(255,255,255,0.18)";
        ctx.beginPath();
        ctx.moveTo(midX, y0 + 2);
        ctx.lineTo(midX, y0 + cellH - 3);
        ctx.stroke();

        // Balance bar: grows from centre toward the dominant hemisphere.
        const v = vals[r] ?? 0;
        const pos = Math.max(-1, Math.min(1, v / FULL_SCALE));
        const endX = midX + pos * halfW;
        ctx.fillStyle = pos >= 0 ? warm : cool;
        ctx.fillRect(
          Math.min(midX, endX),
          midY - barH / 2,
          Math.max(1, Math.abs(endX - midX)),
          barH,
        );
        // Bright thumb at the bar end.
        ctx.fillStyle = "#e8eefc";
        ctx.fillRect(endX - 1, midY - barH / 2 - 1, 2, barH + 2);
      }
    }
    this.drawColLabels(BAND_ORDER, cellW);
    this.drawRowLabels(regions, cellH);
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
