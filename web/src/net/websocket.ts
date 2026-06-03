import type { ServerMessage } from "./protocol";
import { isFrame, isStatus } from "./protocol";

type StatusHandler = (m: import("./protocol").StatusPayload) => void;
type FrameHandler = (m: import("./protocol").EEGFramePayload) => void;

/**
 * Resilient WebSocket client for /ws/eeg with auto-reconnect.
 * Routes incoming messages to status/frame handlers.
 */
export class EEGSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectDelay = 500;
  private readonly maxDelay = 5000;
  private closed = false;

  onStatus: StatusHandler = () => {};
  onFrame: FrameHandler = () => {};
  onOpen: () => void = () => {};
  onClose: () => void = () => {};

  constructor(path = "/ws/eeg") {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.url = `${proto}://${location.host}${path}`;
  }

  connect(): void {
    this.closed = false;
    this.open();
  }

  private open(): void {
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectDelay = 500;
      this.onOpen();
    };

    ws.onmessage = (ev) => {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      if (isStatus(msg)) this.onStatus(msg);
      else if (isFrame(msg)) this.onFrame(msg);
    };

    ws.onclose = () => {
      this.onClose();
      if (!this.closed) this.scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private scheduleReconnect(): void {
    setTimeout(() => {
      if (!this.closed) this.open();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 1.6, this.maxDelay);
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
