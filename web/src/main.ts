import { App } from "./app";
import { installKeyboard } from "./controls/keyboard";
import { installGUI } from "./controls/gui";

const container = document.getElementById("app")!;
const app = new App(container);

installGUI(app);
installKeyboard(app);

app.start().catch((err) => {
  console.error("Failed to start EEG Awesome 3D:", err);
  const status = document.getElementById("status");
  if (status) status.textContent = "startup error — see console";
});
