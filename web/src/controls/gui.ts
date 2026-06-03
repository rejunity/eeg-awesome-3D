import GUI from "lil-gui";
import type { App } from "../app";
import { PRESETS } from "../scene/presets";

const BANDS = ["delta", "theta", "alpha", "beta", "gamma"];

/**
 * Runtime GUI (lil-gui), recreating the spirit of the Unity controls:
 * preset selection, electrode colour mode/band, head opacity, trace invert,
 * indicator toggle, and a debug-electrode selector.
 */
export function installGUI(app: App): GUI {
  const gui = new GUI({ title: "EEG Awesome 3D" });

  const state = {
    preset: PRESETS[0].name,
    display: "none",
    colorMode: "redgreen",
    band: "alpha",
    headCutaway: 1.0,
    indicators: true,
    invertTrace: false,
    autoRotate: false,
    debugElectrode: "(none)",
  };

  gui
    .add(state, "preset", PRESETS.map((p) => p.name))
    .name("Preset")
    .onChange((name: string) => {
      app.applyPreset(PRESETS.findIndex((p) => p.name === name));
    });

  gui
    .add(state, "display", ["none", "trace", "bands", "fft"])
    .name("Display")
    .listen()
    .onChange((mode: string) => app.setDisplay(mode as any));

  gui
    .add(state, "colorMode", ["redgreen", "band"])
    .name("Electrode colour")
    .onChange((m: string) => app.electrodes.setColorMode(m as any));

  gui
    .add(state, "band", BANDS)
    .name("Band")
    .onChange((b: string) => app.electrodes.setBand(b));

  gui
    .add(state, "headCutaway", 0, 1, 0.01)
    .name("Head cutaway")
    .onChange((v: number) => app.brainHead.setCutaway(v));

  gui
    .add(state, "indicators")
    .name("Indicators")
    .listen()
    .onChange((v: boolean) => app.electrodes.setIndicatorsVisible(v));

  gui
    .add(state, "invertTrace")
    .name("Invert trace")
    .onChange((v: boolean) => app.trace.setInvert(v));

  gui
    .add(state, "autoRotate")
    .name("Auto-rotate")
    .listen()
    .onChange((v: boolean) => app.setAutoRotate(v));

  // Debug electrode selector is populated once electrode metadata is known.
  app.onElectrodesReady((names) => {
    gui
      .add(state, "debugElectrode", ["(none)", ...names])
      .name("Debug electrode")
      .onChange((n: string) =>
        app.electrodes.setDebugElectrode(n === "(none)" ? null : n),
      );
  });

  app.guiState = state;
  return gui;
}
