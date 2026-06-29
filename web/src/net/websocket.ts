import type { ServerMessage } from "./protocol";
import { isFrame, isStatus, isStreams } from "./protocol";

type StatusHandler = (m: import("./protocol").StatusPayload) => void;
type FrameHandler = (m: import("./protocol").EEGFramePayload) => void;
type StreamsHandler = (m: import("./protocol").StreamsPayload) => void;

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
  onStreams: StreamsHandler = () => {};
  onOpen: () => void = () => {};
  onClose: () => void = () => {};

  constructor(path = "/ws/eeg") {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    // Under the Vite dev server (port 5173), connect straight to the backend
    // instead of through Vite's WebSocket proxy, which throttles the stream.
    const host = location.port === "5173" ? "127.0.0.1:8765" : location.host;
    this.url = `${proto}://${host}${path}`;
  }

  connect(): void {
    this.closed = false;
    this.open();
  }

  /** Send a control message to the backend (no-op if not connected). */
  send(message: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  private open(): void {
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectDelay = 500;
      this.onOpen();
    };

    ws.onmessage = (ev) => {
      let msg: ServerMessage | { type: "batch"; messages: ServerMessage[] };
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      // The server batches all frames accumulated since the last flush into one
      // message; unwrap and route each. Single messages are still handled.
      if ((msg as { type: string }).type === "batch") {
        for (const m of (msg as { messages: ServerMessage[] }).messages) {
          this.route(m);
        }
      } else {
        this.route(msg as ServerMessage);
      }
    };

    ws.onclose = () => {
      this.onClose();
      if (!this.closed) this.scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private route(m: ServerMessage): void {
    if (isStatus(m)) this.onStatus(m);
    else if (isFrame(m)) this.onFrame(m);
    else if (isStreams(m)) this.onStreams(m);
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
