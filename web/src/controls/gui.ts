import GUI from "lil-gui";
import type { App } from "../app";
import { BrainHead } from "../scene/brainHead";
import type { ElectrodeShape } from "../scene/electrodes";
import type { ColorScheme } from "../scene/colormap";

const BANDS = ["none", "delta", "theta", "alpha", "beta", "gamma", "custom"];

// Display modes: label -> internal mode value.
const DISPLAYS: Record<string, string> = {
  none: "none",
  trace: "trace",
  "raw signal": "rawtrace",
  bands: "bands",
  fft: "fft",
  features: "features",
};

// Curated electrode colour sources: the filtered signal, its power envelope,
// band powers, and the most useful per-channel features. Inert entries
// (processor not enabled) simply leave the electrodes unchanged.
const ELECTRODE_SOURCES = [
  "signal", "power",
  "alpha", "beta", "theta", "delta", "gamma",
  "rel_alpha", "theta_beta", "engagement",
  "hjorth_mobility", "hjorth_complexity", "line_length",
  "spectral_entropy", "aperiodic_slope", "env_alpha", "env_beta",
];

// A bandpass edge slider with exponential (log) scaling 1..120 Hz, so low
// frequencies get far more resolution than high ones. Exposes the current Hz
// and a setter so a band preset can sync the slider position.
function logHzSlider(
  folder: GUI,
  initHz: number,
  label: string,
  onChange: (hz: number) => void,
) {
  const MIN = 1;
  const MAX = 120;
  const clamp = (h: number) => Math.max(MIN, Math.min(MAX, h));
  const toT = (hz: number) => Math.log(clamp(hz) / MIN) / Math.log(MAX / MIN);
  const toHz = (t: number) => MIN * Math.pow(MAX / MIN, t);
  const proxy = { t: toT(initHz) };
  const ctrl = folder.add(proxy, "t", 0, 1, 0.0001);
  const refresh = () => ctrl.name(`${label}: ${toHz(proxy.t).toFixed(1)} Hz`);
  ctrl.onChange(() => {
    refresh();
    onChange(toHz(proxy.t));
  });
  refresh();
  return {
    hz: () => toHz(proxy.t),
    setHz: (hz: number) => {
      proxy.t = toT(hz);
      refresh();
      ctrl.updateDisplay();
    },
  };
}

/**
 * Runtime GUI (lil-gui): display mode, electrode colour scheme/source, the
 * global filter chain (bandpass band + log Hz sliders, notch), head opacity,
 * trace invert, indicator toggle, and a debug-electrode selector.
 */
export function installGUI(app: App): GUI {
  const gui = new GUI({ title: "EEG Awesome 3D" });

  const state = {
    display: "trace",
    band: app.bandDefault,
    bandRunMode: app.bandRunDefaults.mode,
    bandRunHz: app.bandRunDefaults.hz,
    bandpassOn: app.filterDefaults.bandpassOn,
    bandpassLow: app.filterDefaults.bandpassLow,
    bandpassHigh: app.filterDefaults.bandpassHigh,
    notchOn: app.filterDefaults.notchOn,
    notchHz: app.filterDefaults.notchHz,
    fftSource: app.filterDefaults.fftSource,
    electrodeSource: app.electrodeSourceDefault,
    colorScheme: "blue-yellow",
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
    .add(state, "display", DISPLAYS)
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

  // Electrode colouring: which per-channel quantity drives the 3D electrodes.
  gui
    .add(state, "electrodeSource", ELECTRODE_SOURCES)
    .name("Electrode source")
    .onChange((v: string) => app.setElectrodeSource(v));

  // Global filter front-end. The band selector sets the bandpass to standard
  // band edges; "custom" uses the low/high sliders (set low > high to REJECT
  // that band). Everything downstream — trace, electrodes, features, FFT — sees
  // the filtered signal. Flip "FFT source" to raw to compare against the input.
  const filters = gui.addFolder("Filters (global)");
  // Bandpass edges use exponential sliders (more resolution at low Hz).
  const lowSlider = logHzSlider(filters, app.filterDefaults.bandpassLow, "Low", (hz) =>
    app.setBandpassRange(hz, highSlider.hz()),
  );
  const highSlider = logHzSlider(filters, app.filterDefaults.bandpassHigh, "High", (hz) =>
    app.setBandpassRange(lowSlider.hz(), hz),
  );
  filters
    .add(state, "band", BANDS)
    .name("Bandpass band")
    .listen()
    .onChange((b: string) => {
      app.setBand(b);
      const [lo, hi] = app.bandpassRange;
      lowSlider.setHz(lo);
      highSlider.setHz(hi);
    });
  filters
    .add(state, "notchOn")
    .name("Notch on")
    .onChange((v: boolean) => app.setNotch({ on: v }));
  filters
    .add(state, "notchHz", { "50Hz Europe": 50, "60Hz US": 60 })
    .name("Notch (Hz)")
    .onChange((v: number) => app.setNotch({ hz: v }));
  filters
    .add(state, "fftSource", ["filtered", "raw"])
    .name("FFT source")
    .onChange((v: string) => app.setFftSource(v));

  // Feature-extractor recompute cadence (throttles bands/features, not the trace).
  const adv = gui.addFolder("Extractor cadence");
  adv
    .add(state, "bandRunMode", ["realtime", "frequency", "per-sample"])
    .name("Run mode")
    .onChange((m: string) => app.setBandRun(m, state.bandRunHz));
  adv
    .add(state, "bandRunHz", 1, 60, 1)
    .name("Run Hz (freq)")
    .onChange((hz: number) => app.setBandRun(state.bandRunMode, hz));
  adv.close();

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
