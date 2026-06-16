import { Color } from "three";

/**
 * Colour mapping ported from Unity's MixEEGColors:
 *   lerp(red, green, eeg/2 + 0.5) * 0.4
 * Input is the centered normalized value in [-1, 1].
 */
const RED = new Color(1, 0, 0);
const GREEN = new Color(0, 1, 0);

export function redGreen(normalized: number, intensity = 1.0): Color {
  const t = Math.min(1, Math.max(0, normalized * 0.5 + 0.5));
  return new Color().lerpColors(RED, GREEN, t).multiplyScalar(0.4 * intensity * 2.0);
}

export type ColorScheme = "red-green" | "blue-yellow" | "black-white";

/**
 * Electrode colour for a value in [-1, 1].
 *   red-green / blue-yellow: diverging, black-centred (0 = running mean);
 *     brightness encodes the signed deviation.
 *   black-white (absolute): grayscale of the *magnitude*, gamma 2.2, scaled by
 *     ``sd`` (the Color SD control) as a brightness gain.
 */
export function electrodeColor(
  value: number,
  scheme: ColorScheme = "red-green",
  sd = 1,
): Color {
  const v = Math.min(1, Math.max(-1, value));
  if (scheme === "black-white") {
    const g = Math.min(1, Math.pow(Math.abs(v), 2.2) * sd);
    return new Color(g, g, g);
  }
  if (scheme === "blue-yellow") {
    return v >= 0 ? new Color(v, v, 0) : new Color(0, 0, -v);
  }
  return v >= 0 ? new Color(0, v, 0) : new Color(-v, 0, 0);
}

/** Band-energy colours for the short-Fourier / band display modes. */
export const BAND_COLORS: Record<string, Color> = {
  delta: new Color(0.4, 0.2, 0.8),
  theta: new Color(0.2, 0.5, 0.9),
  alpha: new Color(0.2, 0.9, 0.6),
  beta: new Color(0.9, 0.8, 0.2),
  gamma: new Color(0.9, 0.3, 0.3),
};

// Inferno-like heat ramp: BLACK at 0 (so zero energy is truly black, not a
// washed-out bias colour) rising through indigo -> magenta -> orange -> pale
// yellow, for high contrast across the band/FFT panels.
const HEAT_STOPS: Array<[number, [number, number, number]]> = [
  [0.0, [0.0, 0.0, 0.0]],
  [0.14, [0.12, 0.02, 0.25]], // deep indigo
  [0.32, [0.42, 0.04, 0.43]], // purple
  [0.52, [0.74, 0.14, 0.27]], // magenta-red
  [0.72, [0.96, 0.42, 0.09]], // orange
  [0.88, [0.99, 0.73, 0.21]], // amber
  [1.0, [1.0, 0.98, 0.78]], // pale yellow
];

/** Diverging colour for a signed value in [-1, 1]: positive -> warm (right),
 *  negative -> cool (left), 0 -> black; |value| sets brightness. */
export function diverging(value: number): Color {
  const x = Math.min(1, Math.max(-1, value));
  return x >= 0 ? new Color(x, 0.25 * x, 0) : new Color(0, 0.25 * -x, -x);
}

/** Map a [0,1] energy to a black-based heat colour for band/FFT panels. */
export function heat(value: number): Color {
  const v = Math.min(1, Math.max(0, value));
  for (let i = 1; i < HEAT_STOPS.length; i++) {
    const [t1, c1] = HEAT_STOPS[i];
    if (v <= t1) {
      const [t0, c0] = HEAT_STOPS[i - 1];
      const f = t1 > t0 ? (v - t0) / (t1 - t0) : 0;
      return new Color(
        c0[0] + (c1[0] - c0[0]) * f,
        c0[1] + (c1[1] - c0[1]) * f,
        c0[2] + (c1[2] - c0[2]) * f,
      );
    }
  }
  const last = HEAT_STOPS[HEAT_STOPS.length - 1][1];
  return new Color(last[0], last[1], last[2]);
}
