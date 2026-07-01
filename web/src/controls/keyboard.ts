import type { App, DisplayMode, ElectrodeSort } from "../app";

// Bandpass band by key: letters (mnemonic) + 0 = none.
const BAND_KEYS: Record<string, string> = {
  "0": "none",
  d: "delta",
  t: "theta",
  a: "alpha",
  b: "beta",
  g: "gamma",
};

// Electrode row-sort for the top panel: z = default, then region initials.
const SORT_KEYS: Record<string, ElectrodeSort> = {
  z: "default",
  l: "left",
  r: "right",
  c: "central",
  o: "occipital",
  f: "frontal",
  p: "parietal",
};

// Top display panels selected sequentially by the number keys 1..N.
const TAB_ORDER: Exclude<DisplayMode, "none">[] = [
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
 *   a/b/g/d/t : bandpass alpha/beta/gamma/delta/theta;  0 / Esc = none
 *   z/l/r/c/o/f/p : electrode row-sort (default/left/right/central/
 *                   occipital/frontal/parietal)
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
      case "Escape":
        app.setBand("none"); // disable the global bandpass
        break;
      default: {
        // 1..N select a top panel sequentially; pressing the active one closes it.
        if (e.key >= "1" && e.key <= "9") {
          const idx = Number(e.key) - 1;
          if (idx < TAB_ORDER.length) app.toggleDisplay(TAB_ORDER[idx]);
          break;
        }
        const key = e.key.toLowerCase();
        // Electrode row-sort for the top panel (z/l/r/c/o/f/p).
        const sort = SORT_KEYS[key];
        if (sort) {
          app.setElectrodeSort(sort);
          break;
        }
        // Letters (+ 0) select the bandpass band.
        const band = BAND_KEYS[key];
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
