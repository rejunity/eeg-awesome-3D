import { CanvasTexture, LinearFilter } from "three";

/**
 * Scrolling EEG strip chart on an offscreen canvas, uploaded as a CanvasTexture
 * (PLAN.md Option A). Recreates the Unity eegDisplayRT: one vertical column is
 * advanced per frame, each channel drawn as a stacked horizontal trace with
 * configurable overlap and an invert mode.
 */
// Minimum row height (px) needed to keep a channel label legible; the panel
// shows as many channels as fit at this row height.
const MIN_ROW_HEIGHT = 16;
const LABEL_GUTTER = 34; // px reserved on the left for channel names

export class EEGTraceTexture {
  readonly texture: CanvasTexture;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private writeX = LABEL_GUTTER;
  private prev: number[] = [];
  private invert = false;
  private channelsToDisplay = 64;
  private overlap = 0.25;
  private names: string[] = [];

  constructor(width = 1024, height = 256) {
    this.canvas = document.createElement("canvas");
    this.canvas.width = width;
    this.canvas.height = height;
    this.ctx = this.canvas.getContext("2d")!;
    this.clear();
    this.texture = new CanvasTexture(this.canvas);
    this.texture.minFilter = LinearFilter;
    this.texture.magFilter = LinearFilter;
  }

  /** The backing canvas, for displaying the trace as a 2D DOM overlay. */
  get domElement(): HTMLCanvasElement {
    return this.canvas;
  }

  setInvert(invert: boolean): void {
    this.invert = invert;
    this.clear();
  }

  setChannelsToDisplay(n: number): void {
    this.channelsToDisplay = Math.max(1, n);
  }

  setOverlap(o: number): void {
    this.overlap = Math.max(0, o);
  }

  private clear(): void {
    this.ctx.fillStyle = this.invert ? "#ffffff" : "#05070d";
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
  }

  /**
   * Advance one column and plot the latest per-channel values. ``names`` (in the
   * same order) are drawn as labels in a left gutter. As many channels as fit
   * the panel (at MIN_ROW_HEIGHT) are shown.
   */
  push(normalized: number[], names: string[] = []): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    this.names = names;
    const fit = Math.max(1, Math.floor(height / MIN_ROW_HEIGHT));
    const n = Math.min(normalized.length, this.channelsToDisplay, fit);
    if (n === 0) return;

    const plotW = width - LABEL_GUTTER;
    // Fade the new column to background (scrolling trail).
    ctx.fillStyle = this.invert ? "rgba(255,255,255,0.5)" : "rgba(5,7,13,0.5)";
    ctx.fillRect(this.writeX, 0, 2, height);

    // Rows span the full panel height; overlap widens the trace amplitude
    // (so adjacent channels overlap) rather than shrinking the used height.
    const rowSpacing = height / n;
    const amplitude = rowSpacing * 0.5 * (1 + this.overlap);
    ctx.strokeStyle = this.invert ? "#101418" : "#a6e3f0";
    ctx.lineWidth = 1;

    for (let i = 0; i < n; i++) {
      const v = normalized[i] ?? 0; // [-1, 1]
      const prev = this.prev[i] ?? v;
      const baseline = rowSpacing * (i + 0.5);
      const y = baseline - v * amplitude;
      const yPrev = baseline - prev * amplitude;
      const xPrev =
        LABEL_GUTTER + ((this.writeX - 1 - LABEL_GUTTER + plotW) % plotW);
      ctx.beginPath();
      ctx.moveTo(xPrev, yPrev);
      ctx.lineTo(this.writeX, y);
      ctx.stroke();
    }

    this.prev = normalized.slice(0, n);
    this.writeX = LABEL_GUTTER + ((this.writeX + 1 - LABEL_GUTTER) % plotW);

    // Draw a moving cursor bar just ahead of the write head.
    ctx.fillStyle = this.invert ? "#000000" : "#313244";
    ctx.fillRect(
      LABEL_GUTTER + ((this.writeX + 1 - LABEL_GUTTER) % plotW),
      0,
      1,
      height,
    );

    this._drawLabels(n, rowSpacing);
    this.texture.needsUpdate = true;
  }

  /** Redraw the channel-name labels in the left gutter (kept on top each frame). */
  private _drawLabels(n: number, rowSpacing: number): void {
    const ctx = this.ctx;
    const { height } = this.canvas;
    // Opaque gutter so labels stay legible over the scrolling trace.
    ctx.fillStyle = this.invert ? "#ffffff" : "#05070d";
    ctx.fillRect(0, 0, LABEL_GUTTER, height);
    ctx.font = "11px ui-monospace, monospace";
    ctx.textBaseline = "middle";
    ctx.fillStyle = this.invert ? "#101418" : "#a6e3f0";
    for (let i = 0; i < n; i++) {
      const label = this.names[i] ?? String(i);
      ctx.fillText(label, 3, rowSpacing * (i + 0.5));
    }
  }
}
