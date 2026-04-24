type MessageHandler = (msg: Record<string, unknown>) => void;

export class WsConnection {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: MessageHandler[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private binary: boolean;

  constructor(path: string, binary = false) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.url = `${protocol}//${window.location.host}${path}`;
    this.binary = binary;
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    this.ws = new WebSocket(this.url);
    if (this.binary) this.ws.binaryType = "blob";

    this.ws.onmessage = (ev: MessageEvent) => {
      if (this.binary) {
        this.handlers.forEach((h) => h({ blob: ev.data }));
      } else {
        try {
          const msg = JSON.parse(ev.data as string);
          this.handlers.forEach((h) => h(msg));
        } catch {
          /* ignore parse errors */
        }
      }
    };
    this.ws.onclose = () => {
      this.reconnectTimer = setTimeout(() => this.connect(), 2000);
    };
    this.ws.onerror = () => this.ws?.close();
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.ws?.close();
    this.ws = null;
  }

  onMessage(handler: MessageHandler) {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler);
    };
  }
}
