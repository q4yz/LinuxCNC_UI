// Frontend toast notification store. Surfaces operator-facing
// popups on top of the existing console panel so messages are
// visible without searching the log.
//
// Design notes (issue #99):
//
// * **Pinia store, not a composable factory.** A single instance is
//   the only sensible target — every call site must agree on the
//   active toast list. Using Pinia keeps the toast subscription
//   reactive so the ``<ToastContainer>`` re-renders automatically
//   when new popups arrive.
//
// * **Auto-dismiss vs. persistent.** ``success`` and ``info`` are
//   transient confirmations ("Staged 4 artifact(s)") and disappear
//   after five seconds. ``error`` and ``warn`` persist until the
//   operator explicitly dismisses them — a silent error toast is
//   worse than no toast at all, and a five-second timer would let
//   the operator miss the only chance to read a long error.
//
// * **Duration is configurable per call.** ``success(msg, {
//   durationMs: 1000 })`` overrides the default for callers that
//   know their popup is short-lived.
//
// * **No Vue / DOM imports in this module.** ``ToastContainer.vue``
//   owns the rendering; this file is purely state. Tests can drive
//   the store through ``node --test`` by reading the source — see
//   ``frontend/tests/test-console-features.mjs``.

import { defineStore } from "pinia";

// Default dwell time for transient toast types. Picked to match the
// issue's "5 s" requirement while leaving room for the eye to land
// before the row starts fading.
const DEFAULT_TRANSIENT_DURATION_MS = 5000;

// Stable level vocabulary. Mirrors ``stores/console.js``'s level
// tokens so the toast can colour-code on the same field the
// console panel already knows about. ``command`` is intentionally
// absent — popups for MDI echoes would drown the operator.
export const TOAST_TYPES = ["success", "info", "warn", "error"];

// Maps each toast type to the colour pair the container renders.
// Exposed as a constant so the container and the tests can stay in
// sync without re-deriving the mapping in two places.
export const TOAST_TYPE_STYLES = {
  success: {
    icon: "✓",
    borderClass: "border-l-4 border-green-500",
    iconClass: "text-green-400",
  },
  info: {
    icon: "ℹ",
    borderClass: "border-l-4 border-blue-500",
    iconClass: "text-blue-400",
  },
  warn: {
    icon: "⚠",
    borderClass: "border-l-4 border-amber-500",
    iconClass: "text-amber-400",
  },
  error: {
    icon: "❌",
    borderClass: "border-l-4 border-red-500",
    iconClass: "text-red-400",
  },
};

export const useToastStore = defineStore("toast", {
  state: () => ({
    /**
     * The list of currently visible toasts. Each entry carries the
     * four fields ``ToastContainer.vue`` needs to render + dismiss:
     * ``id``, ``type``, ``title``, ``body``. ``durationMs`` is a
     * hint, not a contract — the container sets the timer.
     */
    toasts: [],
  }),
  actions: {
    /**
     * Append a toast to the queue.
     *
     * Returns the assigned id so callers that need to update or
     * remove the toast later (e.g. progress indicators) can keep
     * a reference. The container also returns the id; both paths
     * are valid.
     */
    _add(type, title, body, opts = {}) {
      if (!TOAST_TYPES.includes(type)) {
        // Defensive: callers should not hit this branch, but a typo
        // would otherwise surface as an "info" toast with no border.
        // eslint-disable-next-line no-console
        console.warn(`[toast] unknown type '${type}'; falling back to 'info'`);
        type = "info";
      }
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      this.toasts.push({
        id,
        type,
        title: title || "",
        body: body || "",
        durationMs: Number.isFinite(opts.durationMs) ? opts.durationMs : null,
        createdAt: Date.now(),
      });
      return id;
    },

    success(body, opts = {}) {
      // Title defaults to the body when none is supplied so a bare
      // ``toast.success('Saved.')`` still reads as a confirmation.
      const title = opts.title || "Success";
      return this._add("success", title, body, {
        ...opts,
        durationMs: Number.isFinite(opts.durationMs)
          ? opts.durationMs
          : DEFAULT_TRANSIENT_DURATION_MS,
      });
    },

    info(body, opts = {}) {
      const title = opts.title || "Info";
      return this._add("info", title, body, {
        ...opts,
        durationMs: Number.isFinite(opts.durationMs)
          ? opts.durationMs
          : DEFAULT_TRANSIENT_DURATION_MS,
      });
    },

    warn(body, opts = {}) {
      // Warnings persist — the operator must acknowledge them.
      const title = opts.title || "Warning";
      return this._add("warn", title, body, opts);
    },

    error(body, opts = {}) {
      // Errors persist. ``title`` defaults to ``"Error"`` so a bare
      // ``toast.error('Compile failed')`` reads as a fault, not as
      // a status update.
      const title = opts.title || "Error";
      return this._add("error", title, body, opts);
    },

    /**
     * Remove a single toast by id. Called from the container's
     * dismiss button and from the auto-dismiss timer.
     */
    dismiss(id) {
      this.toasts = this.toasts.filter((toast) => toast.id !== id);
    },

    /**
     * Drop every visible toast. Called from the container's "Clear
     * all" affordance and from tests that need a clean slate.
     */
    clear() {
      this.toasts = [];
    },
  },
});

/**
 * Convenience composable wrapper. Components import this function
 * rather than ``useToastStore`` directly so the call site reads
 * identically to other Pinia helpers in the project.
 *
 * Returns the same store instance ``useToastStore()`` returns; the
 * indirection is purely cosmetic.
 */
export const useToast = () => useToastStore();

export default useToast;
