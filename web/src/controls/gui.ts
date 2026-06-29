import GUI from "lil-gui";
import type { App } from "../app";
import { BrainHead } from "../scene/brainHead";
import { DEFAULT_LABEL_SCALE, type ElectrodeShape } from "../scene/electrodes";

const BANDS = ["none", "delta", "theta", "alpha", "beta", "gamma", "custom"];

// Curated electrode colour sources (label -> frame key): the filtered signal,
// its power envelope, band powers (sorted as the bandpass bands), then the most
// useful per-channel features. Inert entries (processor not enabled) simply
// leave the electrodes unchanged.
const ELECTRODE_SOURCES: Record<string, string> = {
  signal: "signal",
  power: "power",
  delta_power: "delta",
  theta_power: "theta",
  alpha_power: "alpha",
  beta_power: "beta",
  gamma_power: "gamma",
  rel_alpha: "rel_alpha",
  theta_beta: "theta_beta",
  engagement: "engagement",
  hjorth_mobility: "hjorth_mobility",
  hjorth_complexity: "hjorth_complexity",
  line_length: "line_length",
  spectral_entropy: "spectral_entropy",
  aperiodic_slope: "aperiodic_slope",
  env_alpha: "env_alpha",
  env_beta: "env_beta",
  // Signed L/R asymmetry per band (diverging tint; positive = right stronger).
  asym_delta: "asym_delta",
  asym_theta: "asym_theta",
  asym_alpha: "asym_alpha",
  asym_beta: "asym_beta",
  asym_gamma: "asym_gamma",
};

// A custom bandpass-edge control: an EXPONENTIAL (log) slider over 1..120 Hz —
// so low frequencies get far more resolution — paired with a number box on the
// right where the Hz value can be typed directly. Built as raw DOM and appended
// into a lil-gui folder. Exposes the current Hz and a setter so a band preset
// can sync the slider position.
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

  // Reuse lil-gui's row layout classes; the bar itself is a thin track + fill
  // styled with lil-gui's CSS vars, so it matches the other (neat) sliders.
  const row = document.createElement("div");
  row.className = "controller";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = label;
  const widget = document.createElement("div");
  widget.className = "widget";
  Object.assign(widget.style, {
    display: "flex",
    alignItems: "center",
    gap: "6px",
  } as CSSStyleDeclaration);

  const track = document.createElement("div");
  Object.assign(track.style, {
    position: "relative",
    flex: "1",
    height: "var(--widget-height, 20px)",
    borderRadius: "2px",
    background: "var(--widget-color, #1a1a1a)",
    cursor: "ew-resize",
    overflow: "hidden",
  } as CSSStyleDeclaration);
  const fill = document.createElement("div");
  Object.assign(fill.style, {
    position: "absolute",
    top: "0",
    left: "0",
    height: "100%",
    background: "var(--number-color, #2cc9ff)",
    opacity: "0.55",
    pointerEvents: "none",
  } as CSSStyleDeclaration);
  track.appendChild(fill);

  const box = document.createElement("input");
  box.type = "number";
  box.min = String(MIN);
  box.max = String(MAX);
  box.step = "0.1";
  Object.assign(box.style, {
    flex: "0 0 50px",
    width: "50px",
    background: "var(--widget-color, #1a1a1a)",
    color: "var(--text-color, #ebebeb)",
    border: "0",
    borderRadius: "2px",
    font: "inherit",
    padding: "2px 4px",
  } as CSSStyleDeclaration);

  widget.append(track, box);
  row.append(name, widget);
  folder.$children.appendChild(row);

  let current = clamp(initHz);
  const render = () => {
    fill.style.width = `${toT(current) * 100}%`;
    box.value = current.toFixed(1);
  };
  render();

  const setFromX = (clientX: number) => {
    const r = track.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    current = clamp(toHz(t));
    render();
    onChange(current);
  };
  track.addEventListener("pointerdown", (e) => {
    track.setPointerCapture(e.pointerId);
    setFromX(e.clientX);
  });
  track.addEventListener("pointermove", (e) => {
    if (e.buttons & 1) setFromX(e.clientX);
  });
  box.addEventListener("change", () => {
    const v = parseFloat(box.value);
    if (!Number.isFinite(v)) return;
    current = clamp(v);
    render();
    onChange(current);
  });

  return {
    hz: () => current,
    setHz: (hz: number) => {
      current = clamp(hz);
      render();
    },
  };
}

/**
 * Runtime GUI (lil-gui): display mode, electrode colour scheme/source, the
 * global filter chain (bandpass band + log Hz sliders, notch), head opacity,
 * trace invert, indicator toggle, and a debug-electrode selector.
 */
const DEG = 180 / Math.PI;

export function installGUI(app: App): GUI {
  const gui = new GUI({ title: "EEG Awesome 3D" });
  // The app positions the panel just below the top pane (or just under the
  // display dropdown when the pane is off), so it follows the 3D viewport top
  // and never covers the panel. The display-mode dropdown lives on the pane
  // itself (see App._buildDisplaySelect).
  app.setGuiPanel(gui.domElement);

  const state = {
    band: app.bandDefault,
    bandRunMode: app.bandRunDefaults.mode,
    bandRunHz: app.bandRunDefaults.hz,
    bandpassOn: app.filterDefaults.bandpassOn,
    bandpassLow: app.filterDefaults.bandpassLow,
    bandpassHigh: app.filterDefaults.bandpassHigh,
    carOn: app.filterDefaults.carOn,
    notchOn: app.filterDefaults.notchOn,
    notchHz: app.filterDefaults.notchHz,
    fftSource: app.filterDefaults.fftSource,
    electrodeSource: app.electrodeSourceDefault,
    mainsHum: app.mainsDefaults.on,
    mainsHz: app.mainsDefaults.hz,
    mainsAmp: app.mainsDefaults.amplitude,
    colorScheme: "blue-yellow",
    colorSD: app.colorSDDefault,
    headCutaway: BrainHead.defaults.cutaway,
    indicators: true,
    labels: true,
    invertTrace: false,
    autoRotate: false,
    debugElectrode: "(none)",
    brainScale: BrainHead.defaults.brainScale,
    brainPitch: BrainHead.defaults.brainPitch * DEG,
    electrodePitch: app.electrodeDefaults.pitch * DEG,
    electrodeHeight: app.electrodeDefaults.height,
    electrodeDistance: app.electrodeDefaults.distance,
    labelScale: DEFAULT_LABEL_SCALE,
    electrodeShape: app.electrodeDefaults.shape,
    headLitByElectrodes: app.electrodeDefaults.headLit,
  };

  // Global filter front-end (kept at the top). The band selector sets the
  // bandpass to standard band edges; "custom" uses the low/high sliders (set
  // low > high to REJECT that band). Everything downstream — trace, electrodes,
  // features, FFT — sees the filtered signal. Flip "FFT source" to raw to
  // compare against the input.
  const filters = gui.addFolder("Filters (global)");
  // Band selector sits above the Low/High edges.
  filters
    .add(state, "band", BANDS)
    .name("Bandpass band")
    .listen()
    .onChange((b: string) => app.setBand(b));
  // Bandpass edges: exponential sliders (more resolution at low Hz) with an
  // editable Hz box; styled to match the other lil-gui sliders.
  const lowSlider = logHzSlider(filters, app.filterDefaults.bandpassLow, "Low", (hz) =>
    app.setBandpassRange(hz, highSlider.hz()),
  );
  const highSlider = logHzSlider(filters, app.filterDefaults.bandpassHigh, "High", (hz) =>
    app.setBandpassRange(lowSlider.hz(), hz),
  );
  // Keep the Low/High sliders in sync when the band changes from anywhere
  // (band dropdown, ~/0–5 keys, presets).
  app.setBandpassSliderSync(() => {
    const [lo, hi] = app.bandpassRange;
    lowSlider.setHz(lo);
    highSlider.setHz(hi);
  });
  filters
    .add(state, "carOn")
    .name("CAR (common avg ref)")
    .onChange((v: boolean) => app.setCar(v));
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

  gui
    .add(state, "colorScheme", {
      "red-green": "red-green",
      "blue-yellow": "blue-yellow",
      "black-white (absolute)": "black-white",
      "black-yellow (absolute)": "black-yellow",
    })
    .name("Color scheme")
    .onChange((v: string) => app.setColorScheme(v));

  gui
    .add(state, "colorSD", 0.5, 6.0, 0.1)
    .name("Color SD (±σ)")
    .onChange((v: number) => app.setColorSD(v));

  // Electrode colouring: which per-channel quantity drives the 3D electrodes.
  gui
    .add(state, "electrodeSource", ELECTRODE_SOURCES)
    .name("Electrode source")
    .onChange((v: string) => app.setElectrodeSource(v));

  // Anatomy: tune the brain fit and electrode-array pitch at runtime.
  const anatomy = gui.addFolder("Anatomy");
  anatomy
    .add(state, "headCutaway", 0, 1, 0.01)
    .name("Head cutaway")
    .onChange((v: number) => app.brainHead.setCutaway(v));
  anatomy
    .add(state, "brainScale", 0.5, 3.0, 0.01)
    .name("Brain scale")
    .onChange((v: number) => app.brainHead.setBrainScale(v));
  anatomy
    .add(state, "brainPitch", -45, 45, 1)
    .name("Brain pitch (°)")
    .onChange((v: number) => app.brainHead.setBrainPitch(v / DEG));
  anatomy
    .add(state, "electrodePitch", -45, 45, 1)
    .name("Electrode pitch (°)")
    .onChange((v: number) => app.setElectrodePitch(v / DEG));
  anatomy
    .add(state, "electrodeHeight", -1.5, 1.5, 0.01)
    .name("Electrode height")
    .onChange((v: number) => app.setElectrodeVerticalOffset(v));
  anatomy
    .add(state, "electrodeDistance", 0.0, 0.4, 0.005)
    .name("Electrode distance")
    .onChange((v: number) => app.setElectrodeDistance(v));
  anatomy
    .add(state, "labelScale", 0.3, 3.0, 0.05)
    .name("Label scale")
    .onChange((v: number) => app.electrodes.setLabelScale(v));
  anatomy
    .add(state, "electrodeShape", ["sphere", "cone"])
    .name("Electrode shape")
    .onChange((v: string) => app.setElectrodeShape(v as ElectrodeShape));
  anatomy
    .add(state, "headLitByElectrodes")
    .name("Head lit by electrodes")
    .onChange((v: boolean) => app.setHeadLitByElectrodes(v));
  anatomy.close();

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

  // Debug (kept at the very bottom): synthetic mains-hum injection so the notch
  // (and CAR) are demonstrable out of the box, plus the debug-electrode probe.
  const debug = gui.addFolder("Debug");
  debug
    .add(state, "mainsHum")
    .name("Mains hum (synthetic)")
    .onChange((v: boolean) => app.setMainsHum({ on: v }));
  debug
    .add(state, "mainsHz", { "50Hz Europe": 50, "60Hz US": 60 })
    .name("Hum freq")
    .onChange((v: number) => app.setMainsHum({ hz: v }));
  debug
    .add(state, "mainsAmp", 0, 3, 0.05)
    .name("Hum power (×signal)")
    .onChange((v: number) => app.setMainsHum({ amplitude: v }));
  // Debug-electrode selector is populated once electrode metadata is known.
  app.onElectrodesReady((names) => {
    debug
      .add(state, "debugElectrode", ["(none)", ...names])
      .name("Debug electrode")
      .onChange((n: string) =>
        app.electrodes.setDebugElectrode(n === "(none)" ? null : n),
      );
  });
  debug.close();

  // Toggles at the very bottom of the panel.
  gui
    .add(state, "indicators")
    .name("Indicators")
    .listen()
    .onChange((v: boolean) => app.electrodes.setIndicatorsVisible(v));
  gui
    .add(state, "labels")
    .name("Electrode labels")
    .onChange((v: boolean) => app.electrodes.setLabelsVisible(v));
  gui
    .add(state, "invertTrace")
    .name("Invert trace")
    .onChange((v: boolean) => app.trace.setInvert(v));
  gui
    .add(state, "autoRotate")
    .name("Auto-rotate")
    .listen()
    .onChange((v: boolean) => app.setAutoRotate(v));

  app.guiState = state;
  return gui;
}
