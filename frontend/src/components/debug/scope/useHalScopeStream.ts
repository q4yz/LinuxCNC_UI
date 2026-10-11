// WebSocket client for `/ws/hal-scope` (machine backend). Open only while
// the scope has channels; re-sends `configure` when the pin set or the
// sample rate changes and reconnects after a drop. Frames go straight
// into the non-reactive `ScopeBuffer`; only status is reactive.

import { markRaw, onBeforeUnmount, ref, watch, type Ref } from "vue";

import { ScopeBuffer, type ScopeFrame } from "./ScopeBuffer";

const RECONNECT_MS = 1500;

export type StreamStatus = "idle" | "connecting" | "streaming" | "error";

export function scopeSocketUrl(location: Pick<Location, "protocol" | "host"> = window.location): string {
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/hal-scope`;
}

export function useHalScopeStream(pins: Ref<string[]>, rateHz: Ref<number>) {
  const buffer = markRaw(new ScopeBuffer(60));
  const status = ref<StreamStatus>("idle");
  const error = ref("");

  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  function configure(): void {
    if (socket?.readyState !== WebSocket.OPEN) return;
    if (pins.value.length === 0) {
      socket.send(JSON.stringify({ type: "stop" }));
      return;
    }
    buffer.reset(pins.value);
    socket.send(JSON.stringify({ type: "configure", pins: pins.value, rate_hz: rateHz.value }));
  }

  function onMessage(event: MessageEvent): void {
    let message: { type?: string; message?: string } & Partial<ScopeFrame>;
    try {
      message = JSON.parse(String(event.data));
    } catch {
      return;
    }
    if (message.type === "samples" && message.pins && message.t && message.v) {
      buffer.append(message as ScopeFrame);
      status.value = "streaming";
    } else if (message.type === "config") {
      status.value = "streaming";
      error.value = "";
    } else if (message.type === "error") {
      error.value = message.message ?? "scope error";
    }
  }

  function connect(): void {
    if (disposed || socket || pins.value.length === 0) return;
    status.value = "connecting";
    const ws = new WebSocket(scopeSocketUrl());
    socket = ws;
    ws.onopen = () => configure();
    ws.onmessage = onMessage;
    ws.onerror = () => {
      error.value = "Oscilloscope connection failed (is the machine backend running?)";
    };
    ws.onclose = () => {
      socket = null;
      if (disposed || pins.value.length === 0) {
        status.value = "idle";
        return;
      }
      status.value = "error";
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, RECONNECT_MS);
    };
  }

  function disconnect(): void {
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    const ws = socket;
    socket = null;
    ws?.close();
    status.value = "idle";
  }

  watch(
    [() => pins.value.join("\n"), rateHz],
    () => {
      if (pins.value.length === 0) disconnect();
      else if (!socket) connect();
      else configure();
    },
    { immediate: true },
  );

  onBeforeUnmount(() => {
    disposed = true;
    disconnect();
  });

  return { buffer, status, error };
}
