import type { App } from "../app";
import { PRESETS } from "../scene/presets";

/**
 * Keyboard controls mirroring Unity's Controls.cs:
 *   Space : toggle electrode indicators
 *   Z     : EEG strip display
 *   X     : electrode/band display
 *   C     : FFT display
 *   1–7   : visual presets
 *   ↑/↓   : head cutaway / transparency
 */
export function installKeyboard(app: App): void {
  const held = new Set<string>();

  window.addEventListener("keydown", (e) => {
    held.add(e.key);
    switch (e.key) {
      case " ":
        app.electrodes.toggleIndicators();
        e.preventDefault();
        break;
      case "z":
      case "Z":
        app.toggleDisplay("trace");
        break;
      case "x":
      case "X":
        app.toggleDisplay("bands");
        break;
      case "c":
      case "C":
        app.toggleDisplay("fft");
        break;
      default:
        if (e.key >= "1" && e.key <= "7") {
          const idx = Number(e.key) - 1;
          if (idx < PRESETS.length) app.applyPreset(idx);
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
