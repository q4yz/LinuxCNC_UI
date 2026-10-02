// Shared optimistic-update state machine for backend-bound form primitives
// (``BaseCheckbox``, ``BaseRange``, ``BaseSelect``).
//
// Contract:
//   * ``modelValue`` is the backend's value. ``null`` / ``undefined`` means
//     "not received yet" — the primitive renders an *unsynced* state and
//     never invents a default.
//   * A user change emits ``update:modelValue`` and shows the requested value
//     (optimistic) until the backend echoes it back through ``modelValue``.
//   * No echo within ``timeoutMs`` → revert to the backend value and log an
//     error.
//   * Parents with no backend read-back confirm by assigning the emitted
//     value to their own ref (``@update:model-value="v => local = v"``).
//   * Parents with no ``update:modelValue`` listener at all get a local-only
//     toggle and a warning, so missing wiring is loud rather than silent.
//
// Every log line is prefixed with the primitive's ``label`` so the console
// says *which* control did what.

import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useConsoleStore } from '../stores/console'

export const DEFAULT_SYNC_TIMEOUT_MS = 3000

export interface BackendSyncOptions<T> {
  /** Operator-facing control name used in every log line. */
  label: () => string
  /** Backend value; ``null`` / ``undefined`` = not received yet. */
  source: () => T | null | undefined
  /** Whether the parent listens for ``update:modelValue``. */
  hasListener: () => boolean
  emit: (value: T) => void
  equals?: (a: T, b: T) => boolean
  timeoutMs?: () => number
}

const fmt = (value: unknown) => (value == null ? 'unknown' : String(value))

export function useBackendSync<T>(opts: BackendSyncOptions<T>) {
  const consoleStore = useConsoleStore()
  const equals = opts.equals ?? Object.is

  const isPending = ref(false)
  const optimisticValue = ref(null) as Ref<T | null>
  // Fallback state for parents that bind a value but never listen.
  const localValue = ref(opts.source() ?? null) as Ref<T | null>
  let timeoutId: number | null = null

  const isSynced = computed(() => opts.source() != null)

  const displayValue = computed<T | null>(() => {
    if (!opts.hasListener()) return localValue.value
    if (isPending.value) return optimisticValue.value
    return opts.source() ?? null
  })

  function clearTimer() {
    if (timeoutId !== null) {
      clearTimeout(timeoutId)
      timeoutId = null
    }
  }

  if (!isSynced.value) {
    consoleStore.debug(`${opts.label()}: waiting for backend value (no default assumed)`)
  }

  watch(opts.source, (next, prev) => {
    localValue.value = next ?? null

    if (next == null) {
      if (prev != null) {
        consoleStore.warning(`${opts.label()}: backend value lost (was ${fmt(prev)}), control is unsynced`)
      }
      return
    }

    if (isPending.value && equals(next, optimisticValue.value as T)) {
      isPending.value = false
      clearTimer()
      consoleStore.success(`${opts.label()}: confirmed → ${fmt(next)}`)
      return
    }

    if (prev == null) {
      consoleStore.debug(`${opts.label()}: synced from backend → ${fmt(next)}`)
    }
  })

  function onTimeout() {
    timeoutId = null
    if (!isPending.value) return
    isPending.value = false
    const ms = opts.timeoutMs?.() ?? DEFAULT_SYNC_TIMEOUT_MS
    consoleStore.error(
      `${opts.label()}: backend did not confirm ${fmt(optimisticValue.value)} within ${ms} ms ` +
        `(backend reports ${fmt(opts.source())}). Reverted.`,
      { popup: true },
    )
  }

  /** Request ``next`` from the backend (or toggle locally if unwired). */
  function commit(next: T) {
    if (!opts.hasListener()) {
      localValue.value = next
      consoleStore.warning(
        `${opts.label()}: no update:modelValue listener — set locally to ${fmt(next)}, nothing sent to backend`,
      )
      return
    }

    const current = opts.source()
    if (current != null && equals(next, current)) return

    optimisticValue.value = next
    isPending.value = true
    clearTimer()
    consoleStore.debug(`${opts.label()}: requesting ${fmt(next)} (backend: ${fmt(current)})`)
    // Arm before emitting: a parent that confirms synchronously still
    // resolves through the watcher, which clears this timer.
    timeoutId = window.setTimeout(onTimeout, opts.timeoutMs?.() ?? DEFAULT_SYNC_TIMEOUT_MS)
    opts.emit(next)
  }

  onBeforeUnmount(clearTimer)

  return { displayValue, isPending, isSynced, commit }
}
