import type { App } from "../app";

// Bandpass band by key: ~/§/0 = none, 1..5 = delta..gamma.
const BAND_KEYS: Record<string, string> = {
  "`": "none",
  "~": "none",
  "§": "none",
  "0": "none",
  "1": "delta",
  "2": "theta",
  "3": "alpha",
  "4": "beta",
  "5": "gamma",
};

/**
 * Keyboard controls:
 *   Space   : cycle the top display panel (off/trace/power/raw/bands/fft/features)
 *   Z       : signal trace display
 *   X       : power trace display
 *   R       : raw signal trace display
 *   C       : FFT spectrum display
 *   V       : feature heatmap display
 *   ~/§/0–5 : bandpass band (none/delta/theta/alpha/beta/gamma)
 *   ↑/↓     : head cutaway / transparency
 */
export function installKeyboard(app: App): void {
  const held = new Set<string>();

  window.addEventListener("keydown", (e) => {
    held.add(e.key);
    switch (e.key) {
      case " ":
        app.cycleDisplay();
        e.preventDefault();
        break;
      case "z":
      case "Z":
        app.toggleDisplay("trace");
        break;
      case "x":
      case "X":
        app.toggleDisplay("power"); // power (mean-square envelope) traces
        break;
      case "r":
      case "R":
        app.toggleDisplay("rawtrace"); // raw signal, before filtering
        break;
      case "c":
      case "C":
        app.toggleDisplay("fft");
        break;
      case "v":
      case "V":
        app.toggleDisplay("features"); // feature heatmap (Hjorth, entropy, …)
        break;
      default: {
        const band = BAND_KEYS[e.key];
        if (band) app.setBand(band);
      }
    }
  });

  window.addEventListener("keyup", (e) => held.delete(e.key));

  // Arrow keys adjust the head cutaway continuously while held:
  // Up restores the head, Down slices it away from the top to reveal the brain.
  app.onTick(() => {
    if (held.has("ArrowUp")) app.brainHead.adjustCutoff(0.02);
    if (held.has("ArrowDown")) app.brainHead.adjustCutoff(-0.02);
  });
}
