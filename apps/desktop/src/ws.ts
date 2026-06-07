import { TOKEN, WS_BASE } from "./config";
import type { GatewayMessage } from "./types";

export type SocketStatus = "connecting" | "open" | "closed";

// One WebSocket per session. Reconnects with backoff; surfaces every gateway
// event and connection-status change to the caller.
export class SessionSocket {
  private ws: WebSocket | null = null;
  private closed = false;
  private retry = 0;

  constructor(
    private readonly sessionId: string,
    private readonly onEvent: (event: GatewayMessage) => void,
    private readonly onStatus: (status: SocketStatus) => void,
  ) {}

  connect(): void {
    this.onStatus("connecting");
    const url = `${WS_BASE}/ws/${this.sessionId}?token=${encodeURIComponent(TOKEN)}`;
    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      this.retry = 0;
      this.onStatus("open");
    };
    ws.onmessage = (ev) => {
      this.onEvent(JSON.parse(ev.data) as GatewayMessage);
    };
    ws.onclose = () => {
      this.onStatus("closed");
      if (!this.closed) {
        this.retry += 1;
        const delay = Math.min(500 * this.retry, 5000);
        setTimeout(() => {
          if (!this.closed) this.connect();
        }, delay);
      }
    };
  }

  prompt(text: string): void {
    this.ws?.send(JSON.stringify({ action: "prompt", text }));
  }

  cancel(): void {
    this.ws?.send(JSON.stringify({ action: "cancel" }));
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
