/**
 * Fixed-step → variable-step resampler.
 *
 * EEG samples arrive at a fixed rate but in irregular bursts (e.g. ~32 samples
 * every 200 ms), while the browser renders on a variable clock (rAF). This
 * buffers incoming samples and, on each render, plays back the number of
 * samples that correspond to the real time elapsed — turning bursty arrivals
 * into a steady stream aligned to the render clock.
 *
 * Each "sample" is a per-channel number[]; push() appends, drain(now) returns
 * the rows to render this frame. A bounded backlog keeps playback near-live:
 * if arrivals outpace rendering the oldest samples are dropped, and extra
 * samples are released to catch up rather than drifting ever further behind.
 */
export class Resampler {
  private buffer: number[][] = [];
  private rate = 160; // samples/sec (set from the stream's sample rate)
  private lastT = 0;
  private readonly maxLatencySec = 0.3;

  setRate(rate: number): void {
    if (rate > 0) this.rate = rate;
  }

  push(rows: number[][]): void {
    for (const row of rows) this.buffer.push(row);
    // Hard cap so a stalled renderer can't grow the buffer without bound.
    const cap = Math.ceil(this.rate * 2);
    if (this.buffer.length > cap) {
      this.buffer.splice(0, this.buffer.length - cap);
    }
  }

  /** Rows to render for the time elapsed since the last call. */
  drain(nowMs: number): number[][] {
    if (this.lastT === 0) {
      this.lastT = nowMs;
      return [];
    }
    const dt = (nowMs - this.lastT) / 1000;
    this.lastT = nowMs;
    if (this.buffer.length === 0) return [];

    let n = Math.round(dt * this.rate);
    // Catch up if the backlog exceeds the latency budget (keep the trace live).
    const maxBacklog = Math.ceil(this.rate * this.maxLatencySec);
    if (this.buffer.length - n > maxBacklog) {
      n = this.buffer.length - maxBacklog;
    }
    n = Math.max(0, Math.min(n, this.buffer.length));
    return n > 0 ? this.buffer.splice(0, n) : [];
  }
}
