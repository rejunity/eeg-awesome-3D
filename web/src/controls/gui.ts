import GUI from "lil-gui";
import type { App } from "../app";
import { PRESETS } from "../scene/presets";
import { BrainHead } from "../scene/brainHead";
import type { ElectrodeShape } from "../scene/electrodes";
import type { ColorScheme } from "../scene/colormap";

const BANDS = ["none", "delta", "theta", "alpha", "beta", "gamma"];

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
    band: app.bandDefault,
    bandRunMode: app.bandRunDefaults.mode,
    bandRunHz: app.bandRunDefaults.hz,
    bandpassOn: app.filterDefaults.bandpassOn,
    bandpassLow: app.filterDefaults.bandpassLow,
    bandpassHigh: app.filterDefaults.bandpassHigh,
    notchOn: app.filterDefaults.notchOn,
    notchHz: app.filterDefaults.notchHz,
    fftSource: app.filterDefaults.fftSource,
    colorScheme: "red-green",
    colorSD: app.colorSDDefault,
    headCutaway: BrainHead.defaults.cutaway,
    indicators: true,
    invertTrace: false,
    autoRotate: false,
    debugElectrode: "(none)",
    brainScale: BrainHead.defaults.brainScale,
    brainPitch: BrainHead.defaults.brainPitch,
    electrodePitch: app.electrodeDefaults.pitch,
    electrodeHeight: app.electrodeDefaults.height,
    electrodeDistance: app.electrodeDefaults.distance,
    electrodeShape: app.electrodeDefaults.shape,
    headLitByElectrodes: app.electrodeDefaults.headLit,
  };

  gui
    .add(state, "preset", PRESETS.map((p) => p.name))
    .name("Preset")
    .onChange((name: string) => {
      app.applyPreset(PRESETS.findIndex((p) => p.name === name));
    });

  gui
    .add(state, "display", [
      "none",
      "trace",
      "rawtrace",
      "bands",
      "fft",
      "features",
    ])
    .name("Display")
    .listen()
    .onChange((mode: string) => app.setDisplay(mode as any));

  gui
    .add(state, "colorScheme", ["red-green", "blue-yellow"])
    .name("Color scheme")
    .onChange((v: string) => app.electrodes.setColorScheme(v as ColorScheme));

  gui
    .add(state, "colorSD", 0.5, 6.0, 0.1)
    .name("Color SD (±σ)")
    .onChange((v: number) => app.setColorSD(v));

  gui
    .add(state, "band", BANDS)
    .name("Band processor")
    .listen()
    .onChange((b: string) => app.setBand(b));

  gui
    .add(state, "bandRunMode", ["realtime", "frequency", "per-sample"])
    .name("Filter rate")
    .onChange((m: string) => app.setBandRun(m, state.bandRunHz));
  gui
    .add(state, "bandRunHz", 1, 60, 1)
    .name("Filter Hz (freq)")
    .onChange((hz: number) => app.setBandRun(state.bandRunMode, hz));

  // Global filter front-end: cleans the signal that feeds ALL feature
  // extractors. Narrow the bandpass and flip "FFT source" to filtered to watch
  // the spectrum collapse to the pass-band.
  const filters = gui.addFolder("Filters (global)");
  filters
    .add(state, "bandpassOn")
    .name("Bandpass on")
    .onChange((v: boolean) => app.setBandpass({ on: v }));
  filters
    .add(state, "bandpassLow", 0.1, 60, 0.1)
    .name("Bandpass low (Hz)")
    .onChange((v: number) => app.setBandpass({ low: v, high: state.bandpassHigh }));
  filters
    .add(state, "bandpassHigh", 1, 120, 0.5)
    .name("Bandpass high (Hz)")
    .onChange((v: number) => app.setBandpass({ low: state.bandpassLow, high: v }));
  filters
    .add(state, "notchOn")
    .name("Notch on")
    .onChange((v: boolean) => app.setNotch({ on: v }));
  filters
    .add(state, "notchHz", [50, 60])
    .name("Notch (Hz)")
    .onChange((v: number) => app.setNotch({ hz: v }));
  filters
    .add(state, "fftSource", ["raw", "filtered"])
    .name("FFT source")
    .onChange((v: string) => app.setFftSource(v));

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

  // Anatomy: tune the brain fit and electrode-array pitch at runtime.
  const anatomy = gui.addFolder("Anatomy");
  anatomy
    .add(state, "brainScale", 0.5, 3.0, 0.01)
    .name("Brain scale")
    .onChange((v: number) => app.brainHead.setBrainScale(v));
  anatomy
    .add(state, "brainPitch", -0.8, 0.8, 0.01)
    .name("Brain pitch (rad)")
    .onChange((v: number) => app.brainHead.setBrainPitch(v));
  anatomy
    .add(state, "electrodePitch", -0.8, 0.8, 0.01)
    .name("Electrode pitch (rad)")
    .onChange((v: number) => app.setElectrodePitch(v));
  anatomy
    .add(state, "electrodeHeight", -1.5, 1.5, 0.01)
    .name("Electrode height")
    .onChange((v: number) => app.setElectrodeVerticalOffset(v));
  anatomy
    .add(state, "electrodeDistance", 0.0, 0.4, 0.005)
    .name("Electrode distance")
    .onChange((v: number) => app.setElectrodeDistance(v));
  anatomy
    .add(state, "electrodeShape", ["sphere", "cone"])
    .name("Electrode shape")
    .onChange((v: string) => app.setElectrodeShape(v as ElectrodeShape));
  anatomy
    .add(state, "headLitByElectrodes")
    .name("Head lit by electrodes")
    .onChange((v: boolean) => app.setHeadLitByElectrodes(v));

  app.guiState = state;
  return gui;
}
