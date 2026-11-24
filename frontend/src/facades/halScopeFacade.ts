// HAL oscilloscope stream facade (machine backend ``/ws/hal-scope``): the
// socket and its protocol — ``configure`` / ``stop`` out, ``samples`` /
// ``config`` / ``error`` frames in. Reconnecting and buffering are the
// caller's (``components/debug/scope/useHalScopeStream``).

import type { ScopeFrame } from "../entities/hal/ScopeFrame";
import { withToken } from "../core/authToken";

export interface HalScopeHandlers {
  /** The socket is open: configure it. */
  onOpen(): void;
  /** One block of samples. */
  onSamples(frame: ScopeFrame): void;
  /** The backend accepted a configuration. */
  onConfigured(): void;
  /** The backend reported a problem (bad pin, sampler gone, ...). */
  onError(message: string): void;
  /** The connection failed (no machine backend, network). */
  onFailure(): void;
  /** The socket closed (after a failure, or ``close()``). */
  onClose(): void;
}

export interface HalScopeConnection {
  readonly open: boolean;
  /** Sample ``pins`` at ``rateHz``. */
  configure(pins: string[], rateHz: number): void;
  /** Stop sampling, keep the socket. */
  stop(): void;
  close(): void;
}

/** ``ws(s)://<host>/ws/hal-scope`` for the page's own origin. */
function socketUrl(location: Pick<Location, "protocol" | "host"> = window.location): string {
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/hal-scope`;
}

function connect(handlers: HalScopeHandlers): HalScopeConnection {
  const ws = new WebSocket(withToken(socketUrl()));
  const send = (message: object): void => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  };
  ws.onopen = () => handlers.onOpen();
  ws.onerror = () => handlers.onFailure();
  ws.onclose = () => handlers.onClose();
  ws.onmessage = (event: MessageEvent) => {
    let message: { type?: string; message?: string } & Partial<ScopeFrame>;
    try {
      message = JSON.parse(String(event.data));
    } catch {
      return;
    }
    if (message.type === "samples" && message.pins && message.t && message.v) {
      handlers.onSamples(message as ScopeFrame);
    } else if (message.type === "config") {
      handlers.onConfigured();
    } else if (message.type === "error") {
      handlers.onError(message.message ?? "scope error");
    }
  };
  return {
    get open() {
      return ws.readyState === WebSocket.OPEN;
    },
    configure: (pins, rateHz) => send({ type: "configure", pins, rate_hz: rateHz }),
    stop: () => send({ type: "stop" }),
    close: () => ws.close(),
  };
}

export const halScopeFacade = Object.freeze({ socketUrl, connect });

export default halScopeFacade;
