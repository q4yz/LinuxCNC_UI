// Machine-state entity. Wraps the wire shape produced by the
// backend's ``MachineState`` enum + ``MODE_*`` enums.
//
// ``state`` values mirror the backend's enum:
//   - "idle" | "loaded" | "running" | "paused" | "fault" |
//     "estop" | "off" | "updating"
//
// ``mode`` values mirror the backend:
//   - "manual" | "auto" | "mdi"

export const MACHINE_STATES = Object.freeze([
  "idle",
  "loaded",
  "running",
  "paused",
  "fault",
  "estop",
  "off",
  "updating",
]);

export const MACHINE_MODES = Object.freeze(["manual", "auto", "mdi"]);

export class MachineState {
  /**
   * @param {object} params
   * @param {string} [params.state]
   * @param {string} [params.mode]
   * @param {boolean} [params.isOnline]
   * @param {boolean} [params.isEstopped]
   * @param {string|null} [params.lastError]
   */
  constructor({
    state = "off",
    mode = "manual",
    isOnline = false,
    isEstopped = false,
    lastError = null,
  } = {}) {
    this._state = MACHINE_STATES.includes(state) ? state : "off";
    this._mode = MACHINE_MODES.includes(mode) ? mode : "manual";
    this._isOnline = Boolean(isOnline);
    this._isEstopped = Boolean(isEstopped);
    this._lastError = lastError;
  }

  get state() {
    return this._state;
  }

  get mode() {
    return this._mode;
  }

  get isOnline() {
    return this._isOnline;
  }

  get isEstopped() {
    return this._isEstopped;
  }

  get lastError() {
    return this._lastError;
  }

  get isRunning() {
    return this._state === "running";
  }

  get isLoaded() {
    return this._state === "loaded" || this._state === "running" || this._state === "paused";
  }

  get isPaused() {
    return this._state === "paused";
  }
}
