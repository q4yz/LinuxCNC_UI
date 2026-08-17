// Result of a write-side command dispatched to a facade. Wraps the
// generated client's response in a small typed shape so callers
// never branch on snake_case / discriminated-union details.
//
// ``ok`` is the single source of truth for "did the command land".
// ``commandId`` and ``message`` are operator-facing echo strings;
// ``failureReason`` carries an exception when ``ok`` is false so
// the UI can route the error to the console store.

export class CommandResult {
  /**
   * @param {object} params
   * @param {boolean} params.ok
   * @param {string} [params.commandId]
   * @param {string} [params.message]
   * @param {Error|string|null} [params.failureReason]
   */
  constructor({ ok, commandId = "", message = "", failureReason = null } = {}) {
    this._ok = Boolean(ok);
    this._commandId = commandId;
    this._message = message;
    this._failureReason = failureReason;
  }

  /** True iff the dispatch landed without error. */
  get ok() {
    return this._ok;
  }

  /** True iff the dispatch failed. */
  get failed() {
    return !this._ok;
  }

  get commandId() {
    return this._commandId;
  }

  get message() {
    return this._message;
  }

  /** ``Error``, ``string``, or ``null``. */
  get failureReason() {
    return this._failureReason;
  }

  static success({ commandId = "", message = "" } = {}) {
    return new CommandResult({ ok: true, commandId, message });
  }

  static failure(reason, { commandId = "", message = "" } = {}) {
    return new CommandResult({
      ok: false,
      commandId,
      message,
      failureReason: reason ?? "unknown error",
    });
  }
}
