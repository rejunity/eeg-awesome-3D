import { CanvasTexture, LinearFilter } from "three";

/**
 * Scrolling EEG strip chart on an offscreen canvas, uploaded as a CanvasTexture
 * (PLAN.md Option A). Recreates the Unity eegDisplayRT: one vertical column is
 * advanced per frame, each channel drawn as a stacked horizontal trace with
 * configurable overlap and an invert mode.
 */
export class EEGTraceTexture {
  readonly texture: CanvasTexture;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private writeX = 0;
  private prev: number[] = [];
  private invert = false;
  private channelsToDisplay = 16;
  private overlap = 0.25;

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

  /** Advance one column and plot the latest per-channel normalized values. */
  push(normalized: number[]): void {
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    const n = Math.min(normalized.length, this.channelsToDisplay);
    if (n === 0) return;

    // Fade the new column to background (scrolling trail).
    ctx.fillStyle = this.invert ? "rgba(255,255,255,0.5)" : "rgba(5,7,13,0.5)";
    ctx.fillRect(this.writeX, 0, 2, height);

    const offsetY = height / n / (1 + this.overlap);
    const amplitude = offsetY * 0.9;
    ctx.strokeStyle = this.invert ? "#101418" : "#a6e3f0";
    ctx.lineWidth = 1;

    for (let i = 0; i < n; i++) {
      const v = normalized[i] ?? 0; // [-1, 1]
      const prev = this.prev[i] ?? v;
      const baseline = offsetY * (i + 0.5);
      const y = baseline - v * amplitude;
      const yPrev = baseline - prev * amplitude;
      ctx.beginPath();
      ctx.moveTo((this.writeX - 1 + width) % width, yPrev);
      ctx.lineTo(this.writeX, y);
      ctx.stroke();
    }

    this.prev = normalized.slice(0, n);
    this.writeX = (this.writeX + 1) % width;

    // Draw a moving cursor bar just ahead of the write head.
    ctx.fillStyle = this.invert ? "#000000" : "#313244";
    ctx.fillRect((this.writeX + 1) % width, 0, 1, height);

    this.texture.needsUpdate = true;
  }
}
