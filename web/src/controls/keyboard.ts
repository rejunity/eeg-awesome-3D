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
 *   Tab     : cycle the top display panel (Shift+Tab = reverse)
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

  // True when an editable control (GUI text/number box, dropdown) has focus, so
  // typing numbers etc. isn't hijacked by the display/band shortcuts.
  const isEditing = (): boolean => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return false;
    const tag = el.tagName;
    return (
      tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable
    );
  };

  window.addEventListener("keydown", (e) => {
    if (isEditing()) return; // let the focused control handle the key
    held.add(e.key);
    switch (e.key) {
      case "Tab":
        app.cycleDisplay(e.shiftKey ? -1 : 1);
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
