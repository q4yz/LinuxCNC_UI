// A local control value that follows the same control on every other
// client (#128). ``local`` stays the component's own ref (so a typed or
// dragged value is never overwritten mid-edit by the snapshot); a value
// another client publishes is copied into it, and ``publish()`` sends
// the local value to every client (the machine backend relays it over
// the telemetry WebSocket, see ``stores/sharedValues``).
//
//   const speed = ref(300)
//   const { publish } = useSharedValue(() => `extruder.${id}.speed`, speed)
//   <input v-model.number="speed" @change="publish()">
import { computed, toValue, watch } from "vue";
import type { MaybeRefOrGetter, Ref } from "vue";

import { useSharedValuesStore, type SharedValue } from "../stores/sharedValues";

export interface SharedValueOptions<T> {
  /** Turns a received value into the local one; ``undefined`` ignores it
   * (wrong type, out of range). Default: accept numbers only. */
  accept?: (value: SharedValue) => T | undefined;
  /** The value sent for the local one (default: the local value). */
  toShared?: (value: T) => SharedValue;
}

const acceptNumber = (value: SharedValue) =>
  (typeof value === "number" && Number.isFinite(value) ? value : undefined);

export function useSharedValue<T>(
  key: MaybeRefOrGetter<string>,
  local: Ref<T>,
  options: SharedValueOptions<T> = {},
) {
  const store = useSharedValuesStore();
  const accept = options.accept ?? (acceptNumber as (value: SharedValue) => T | undefined);
  const toShared = options.toShared ?? ((value: T) => value as unknown as SharedValue);

  const shared = computed(() => store.values[toValue(key)]);

  // another client moved it (or this client connected): follow
  watch(shared, (value) => {
    if (value === undefined) return;
    const next = accept(value);
    if (next !== undefined) local.value = next;
  }, { immediate: true });

  /** Send the local value to every client (call on commit, not per keystroke). */
  function publish(): void {
    store.publish(toValue(key), toShared(local.value));
  }

  return { shared, publish };
}
