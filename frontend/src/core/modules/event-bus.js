// Frontend EventBus: cross-module pub/sub. Every subscriber receives
// a deep-frozen, deep-cloned copy of the payload so a buggy handler
// cannot leak mutations to other subscribers. See ``.agent/STATE.md``
// § 3.

/**
 * Deeply freeze a plain object/array so accidental mutation in a
 * subscriber throws (or no-ops) instead of leaking across handlers.
 *
 * @param {*} value
 * @returns {*}
 */
function deepFreeze(value) {
  if (value === null || typeof value !== "object") return value;
  if (Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const key of Object.keys(value)) {
    const inner = /** @type {any} */ (value)[key];
    if (inner && typeof inner === "object" && !Object.isFrozen(inner)) {
      deepFreeze(inner);
    }
  }
  return value;
}

export class EventBus {
  constructor() {
    /** @type {Map<string, Set<Function>>} */
    this._subscribers = new Map();
  }

  /**
   * Register a callback for ``topic``. The callback is invoked as
   * ``callback(topic, payload)``. Subscribers receive a deep-frozen
   * copy of every payload — mutating the copy throws in strict mode
   * and is silently ignored otherwise.
   *
   * @param {string} topic
   * @param {(topic: string, payload: any) => void} callback
   */
  subscribe(topic, callback) {
    if (!this._subscribers.has(topic)) {
      this._subscribers.set(topic, new Set());
    }
    this._subscribers.get(topic).add(callback);
  }

  /**
   * Remove a previously registered callback. Returns true if removed.
   * @param {string} topic
   * @param {Function} callback
   * @returns {boolean}
   */
  unsubscribe(topic, callback) {
    const set = this._subscribers.get(topic);
    if (!set) return false;
    const removed = set.delete(callback);
    if (set.size === 0) this._subscribers.delete(topic);
    return removed;
  }

  /**
   * Synchronously fan-out ``payload`` to every subscriber of ``topic``.
   * Each subscriber receives its own deep-frozen copy.
   *
   * @param {string} topic
   * @param {any} payload
   */
  publish(topic, payload) {
    const set = this._subscribers.get(topic);
    if (!set || set.size === 0) return;
    for (const cb of set) {
      try {
        // Each subscriber gets its own freshly-cloned + deep-frozen
        // copy so a buggy subscriber mutating its copy cannot leak
        // into any other subscriber or the publisher's payload.
        const frozen = deepFreeze(clone(payload));
        cb(topic, frozen);
      } catch (err) {
        // Same policy as the backend bus: one bad subscriber must not
        // prevent the rest from running.
        // eslint-disable-next-line no-console
        console.error(`EventBus subscriber error on ${topic}:`, err);
      }
    }
  }

  /**
   * Return a list of topics with at least one subscriber. Useful for
   * diagnostics in dev tools.
   * @returns {string[]}
   */
  topics() {
    return Array.from(this._subscribers.keys());
  }
}

/**
 * Structural clone for arbitrary JSON-serialisable payloads. We use
 * the browser-native ``structuredClone`` when available (modern
 * Chromium / Firefox / Safari) and fall back to ``JSON.parse(JSON.stringify(...))``
 * for older environments. ``structuredClone`` preserves more types
 * (Date, Map, Set) than the JSON fallback but is fast enough for our
 * payload sizes either way.
 *
 * @param {*} value
 */
function clone(value) {
  if (typeof structuredClone === "function") {
    try {
      return structuredClone(value);
    } catch (_) {
      // structuredClone can throw on unsupported types; fall through.
    }
  }
  return JSON.parse(JSON.stringify(value));
}

// Module-level singleton so modules can ``import { eventBus } from ...``
// without wiring their own bus through the registry.
export const eventBus = new EventBus();

export default eventBus;