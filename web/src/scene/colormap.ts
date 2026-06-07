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

/**
 * Black-centred electrode colour for a value in [-1, 1]:
 *   -1 -> red, 0 (running mean) -> black, +1 -> green.
 * Brightness encodes the magnitude of the deviation; intensity stays constant.
 */
export function electrodeColor(value: number): Color {
  const v = Math.min(1, Math.max(-1, value));
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

/** Map a [0,1] energy to a heat-ish colour for band/FFT panels. */
export function heat(value: number): Color {
  const v = Math.min(1, Math.max(0, value));
  // dark red -> orange -> white-ish, echoing the Unity FFT band colour ramp.
  return new Color().setRGB(0.2 + 0.8 * v, 0.1 + 0.5 * v, 0.1 + 0.6 * v * v);
}
