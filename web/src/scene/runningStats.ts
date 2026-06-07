/**
 * Per-channel running mean and standard deviation, used to map electrode colour
 * without any backend filtering: the raw latest value is converted to a z-score
 * (x - mean) / sd, which the caller then scales by the configured SD span.
 *
 * Uses exponential moving averages of x and x² so the stats track the recent
 * signal (EEG drifts) rather than the all-time mean.
 */
export class RunningStats {
  private mean = new Map<string, number>();
  private meanSq = new Map<string, number>();
  private readonly alpha: number;

  constructor(alpha = 0.02) {
    this.alpha = alpha;
  }

  /** Update channel ``name`` with raw value ``x`` and return its z-score. */
  zscore(name: string, x: number): number {
    const a = this.alpha;
    const prevMean = this.mean.get(name);
    if (prevMean === undefined) {
      // First sample: seed the averages, no deviation yet.
      this.mean.set(name, x);
      this.meanSq.set(name, x * x);
      return 0;
    }
    const mean = (1 - a) * prevMean + a * x;
    const meanSq = (1 - a) * this.meanSq.get(name)! + a * x * x;
    this.mean.set(name, mean);
    this.meanSq.set(name, meanSq);
    const variance = Math.max(meanSq - mean * mean, 1e-12);
    return (x - mean) / Math.sqrt(variance);
  }
}
