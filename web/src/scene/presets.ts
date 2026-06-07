import type { App } from "../app";

/**
 * Visual presets 1–7, recreating the spirit of Unity's Controls.cs setups.
 * Each preset reconfigures head/brain visibility, electrode colour mode, which
 * display texture (if any) is shown, and the cinematic auto-rotate flag.
 */
export interface Preset {
  name: string;
  apply: (app: App) => void;
}

export const PRESETS: Preset[] = [
  {
    name: "Head + brain + raw electrodes",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setCutaway(0.72); // default cutaway, brain peeking through
      app.brainHead.setBrainVisible(true);
      app.electrodes.setIndicatorsVisible(true);
      app.setDisplay("none");
      app.setAutoRotate(false);
    },
  },
  {
    name: "Transparent head cutaway + electrodes",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setCutaway(0.45); // top half cut away to reveal the brain
      app.brainHead.setBrainVisible(true);
      app.electrodes.setIndicatorsVisible(true);
      app.setDisplay("none");
      app.setAutoRotate(false);
    },
  },
  {
    name: "Brain-only electrode energy glow",
    apply: (app) => {
      app.brainHead.setHeadVisible(false);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setIndicatorsVisible(true);
      app.setDisplay("none");
      app.setAutoRotate(false);
    },
  },
  {
    name: "EEG trace panel emphasis",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setCutaway(0.7);
      app.showTrace();
      app.setAutoRotate(false);
    },
  },
  {
    name: "Short-Fourier three-band colour",
    apply: (app) => {
      app.brainHead.setHeadVisible(false);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setIndicatorsVisible(true);
      app.setDisplay("none");
      app.setAutoRotate(false);
    },
  },
  {
    name: "FFT / band matrix",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setCutaway(0.65);
      app.showBands();
      app.setAutoRotate(false);
    },
  },
  {
    name: "Installation / cinematic",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setCutaway(0.9);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setIndicatorsVisible(true);
      app.setDisplay("none");
      app.setAutoRotate(true);
    },
  },
];
