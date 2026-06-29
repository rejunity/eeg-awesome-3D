import type { App, DisplayMode } from "../app";

// Bandpass band by key: letters (mnemonic) + 0 = none.
const BAND_KEYS: Record<string, string> = {
  "0": "none",
  d: "delta",
  t: "theta",
  a: "alpha",
  b: "beta",
  g: "gamma",
};

// Top display panels selected sequentially by the number keys 1..N.
const TAB_ORDER: DisplayMode[] = [
  "trace",
  "power",
  "rawtrace",
  "bands",
  "fft",
  "features",
  "asymmetry",
];

/**
 * Keyboard controls:
 *   Tab       : cycle the top display panel (Shift+Tab = reverse)
 *   1–7       : select the panel sequentially (trace/power/raw/bands/fft/
 *               features/asymmetry)
 *   a/b/g/d/t : bandpass alpha/beta/gamma/delta/theta;  0 = none
 *   ↑/↓       : head cutaway / transparency
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
      default: {
        // 1..N select a top panel sequentially.
        if (e.key >= "1" && e.key <= "9") {
          const idx = Number(e.key) - 1;
          if (idx < TAB_ORDER.length) app.setDisplay(TAB_ORDER[idx]);
          break;
        }
        // Letters (+ 0) select the bandpass band.
        const band = BAND_KEYS[e.key.toLowerCase()];
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
