// stores/sharedValues.ts
// Operator UI values every client shows the same (#128): the sliders
// that steer only the browser (jog speed, the extruder's jog speed and
// distance) and so have no machine pin to read back. The machine
// backend keeps the latest value per key and sends it to every client
// over the telemetry WebSocket (``servoThreadFacade``): ``ui_values``
// (all of them, on connect) and ``ui_value`` (one, when a client moves
// a slider). Components use ``composables/useSharedValue``.
import { defineStore } from "pinia";
import { ref } from "vue";

export type SharedValue = number | string | boolean | null;

type Sender = (key: string, value: SharedValue) => void;
// The transport (``servoThreadFacade`` registers itself): the store
// does not know the WebSocket, and tests plug in their own.
let sender: Sender | null = null;
export function setSharedValueSender(next: Sender | null): void {
  sender = next;
}

export const useSharedValuesStore = defineStore("sharedValues", () => {
  const values = ref<Record<string, SharedValue>>({});

  function apply(key: string, value: SharedValue): void {
    values.value = { ...values.value, [key]: value };
  }

  function replaceAll(next: Record<string, SharedValue>): void {
    values.value = { ...next };
  }

  /** Set locally (optimistic; the backend's echo confirms) and send to every client. */
  function publish(key: string, value: SharedValue): void {
    apply(key, value);
    sender?.(key, value);
  }

  return { values, apply, replaceAll, publish };
});
