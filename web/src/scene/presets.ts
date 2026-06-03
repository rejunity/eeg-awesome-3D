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
      app.brainHead.setHeadOpacity(0.28);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setColorMode("redgreen");
      app.electrodes.setIndicatorsVisible(true);
      app.panel.setVisible(false);
      app.setAutoRotate(false);
    },
  },
  {
    name: "Transparent head cutaway + electrodes",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setHeadOpacity(0.1);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setColorMode("redgreen");
      app.electrodes.setIndicatorsVisible(true);
      app.panel.setVisible(false);
      app.setAutoRotate(false);
    },
  },
  {
    name: "Brain-only electrode energy glow",
    apply: (app) => {
      app.brainHead.setHeadVisible(false);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setColorMode("band");
      app.electrodes.setBand("alpha");
      app.electrodes.setIndicatorsVisible(true);
      app.panel.setVisible(false);
      app.setAutoRotate(false);
    },
  },
  {
    name: "EEG trace panel emphasis",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setHeadOpacity(0.18);
      app.electrodes.setColorMode("redgreen");
      app.showTrace();
      app.setAutoRotate(false);
    },
  },
  {
    name: "Short-Fourier three-band colour",
    apply: (app) => {
      app.brainHead.setHeadVisible(false);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setColorMode("band");
      app.electrodes.setBand("beta");
      app.electrodes.setIndicatorsVisible(true);
      app.panel.setVisible(false);
      app.setAutoRotate(false);
    },
  },
  {
    name: "FFT / band matrix",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setHeadOpacity(0.2);
      app.electrodes.setColorMode("band");
      app.showBands();
      app.setAutoRotate(false);
    },
  },
  {
    name: "Installation / cinematic",
    apply: (app) => {
      app.brainHead.setHeadVisible(true);
      app.brainHead.setHeadOpacity(0.22);
      app.brainHead.setBrainVisible(true);
      app.electrodes.setColorMode("redgreen");
      app.electrodes.setIndicatorsVisible(true);
      app.panel.setVisible(false);
      app.setAutoRotate(true);
    },
  },
];
