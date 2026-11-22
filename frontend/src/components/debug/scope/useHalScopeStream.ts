// The HAL oscilloscope stream (``halScopeFacade``: ``/ws/hal-scope`` on
// the machine backend). Open only while the scope has channels;
// re-sends the configuration when the pin set or the sample rate changes
// and reconnects after a drop. Frames go straight into the non-reactive
// `ScopeBuffer`; only status is reactive.

import { markRaw, onBeforeUnmount, ref, watch, type Ref } from "vue";

import { halScopeFacade, type HalScopeConnection } from "../../../facades/halScopeFacade";
import { ScopeBuffer } from "./ScopeBuffer";

const RECONNECT_MS = 1500;

export type StreamStatus = "idle" | "connecting" | "streaming" | "error";

export function useHalScopeStream(pins: Ref<string[]>, rateHz: Ref<number>) {
  const buffer = markRaw(new ScopeBuffer(60));
  const status = ref<StreamStatus>("idle");
  const error = ref("");

  let socket: HalScopeConnection | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  function configure(): void {
    if (!socket?.open) return;
    if (pins.value.length === 0) {
      socket.stop();
      return;
    }
    buffer.reset(pins.value);
    socket.configure(pins.value, rateHz.value);
  }

  function connect(): void {
    if (disposed || socket || pins.value.length === 0) return;
    status.value = "connecting";
    socket = halScopeFacade.connect({
      onOpen: () => configure(),
      onSamples: (frame) => {
        buffer.append(frame);
        status.value = "streaming";
      },
      onConfigured: () => {
        status.value = "streaming";
        error.value = "";
      },
      onError: (message) => {
        error.value = message;
      },
      onFailure: () => {
        error.value = "Oscilloscope connection failed (is the machine backend running?)";
      },
      onClose: () => {
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
      },
    });
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
