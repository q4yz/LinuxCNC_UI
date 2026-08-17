// Frontend TelemetryBus: high-frequency pub/sub. Payloads are
// delivered by reference so the 100 Hz stream doesn't pay a clone
// cost per tick. Subscribers must clone before storing. See
// ``.agent/STATE.md`` § 3.

/**
 * @typedef {(topic: string, payload: any) => void} TelemetryHandler
 */

export class TelemetryBus {
  constructor() {
    /** @type {Map<string, Set<TelemetryHandler>>} */
    this._subscribers = new Map();
  }

  /**
   * Register a handler for a telemetry topic. The handler is invoked
   * as ``handler(topic, payload)`` synchronously on every publish.
   *
   * @param {string} topic
   * @param {TelemetryHandler} handler
   */
  subscribe(topic, handler) {
    if (!this._subscribers.has(topic)) {
      this._subscribers.set(topic, new Set());
    }
    this._subscribers.get(topic).add(handler);
  }

  /**
   * Remove a previously registered handler.
   * @param {string} topic
   * @param {TelemetryHandler} handler
   * @returns {boolean}
   */
  unsubscribe(topic, handler) {
    const set = this._subscribers.get(topic);
    if (!set) return false;
    const removed = set.delete(handler);
    if (set.size === 0) this._subscribers.delete(topic);
    return removed;
  }

  /**
   * Publish ``payload`` to every subscriber of ``topic`` by reference.
   * No cloning, no freezing — subscribers are expected to be
   * well-behaved consumers in the same process.
   *
   * @param {string} topic
   * @param {any} payload
   */
  publish(topic, payload) {
    const set = this._subscribers.get(topic);
    if (!set || set.size === 0) return;
    for (const handler of set) {
      try {
        handler(topic, payload);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error(`TelemetryBus handler error on ${topic}:`, err);
      }
    }
  }

  /** @returns {string[]} */
  topics() {
    return Array.from(this._subscribers.keys());
  }
}

// Module-level singleton. ``modules/machine/store.js`` publishes
// to it directly until the broadcast loop moves here.
export const telemetryBus = new TelemetryBus();

export default telemetryBus;