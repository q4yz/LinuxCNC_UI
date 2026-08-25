// Result of a write-side command dispatched to a facade. Wraps the
// generated client's response in a small typed shape so callers
// never branch on snake_case / discriminated-union details.
//
// ``ok`` is the single source of truth for "did the command land".
// ``failed`` is a derived convenience getter — UI code should prefer
// ``if (result.failed) { … }`` over negating ``ok`` so the typo class
// of bug ("``!result.success``" returning ``undefined`` instead of a
// boolean) becomes structurally impossible.
//
// ``message`` is the optional wire-echo for success responses (the
// MDI string returned by the backend, a G-code diagnostic, etc.) and
// may be empty. It is *not* settable through ``failure()``; the
// failure path carries its operator-facing text in ``failureReason``.
//
// ``statusCode`` carries the HTTP status from the API error when
// the dispatch failed. ``null`` when the request never produced a
// response (network drop, abort). 2xx is never set explicitly because
// the success path always observes a parsed body.

export type CommandResultParams = {
  ok: boolean;
  commandId?: string;
  message?: string;
  failureReason?: string | null;
  statusCode?: number | null;
};

export type CommandResultSuccessParams = {
  commandId?: string;
  message?: string;
};

export type CommandResultFailureParams = {
  commandId?: string;
  statusCode?: number | null;
  /**
   * @deprecated Use ``failureReason`` (set via the first arg of
   * ``CommandResult.failure(reason, params)``) instead. Accepted
   * here for back-compat with facades that still pass a literal
   * operator-facing fallback like ``"Spindle command failed"``;
   * ignored by the reader — see ``toolStore.ts`` which now keys
   * off ``failureReason``. To be removed once every facade is
   * migrated.
   */
  message?: string;
};

export class CommandResult {
  private readonly _ok: boolean;
  private readonly _commandId: string;
  private readonly _message: string;
  private readonly _failureReason: string | null;
  private readonly _statusCode: number | null;

  constructor(params: CommandResultParams = { ok: true }) {
    this._ok = Boolean(params.ok);
    this._commandId = params.commandId ?? "";
    // ``message`` is the success-only wire echo (MDI string, G-code
    // diagnostic, …). ``CommandResultFailureParams.message`` is
    // accepted for back-compat but intentionally not propagated to
    // ``this._message`` — typed callers key off ``failureReason``.
    this._message = params.ok ? (params.message ?? "") : "";
    this._failureReason = params.ok ? null : (params.failureReason ?? null);
    this._statusCode = params.statusCode ?? null;
  }

  /** True iff the dispatch landed without error. */
  get ok(): boolean {
    return this._ok;
  }

  /** True iff the dispatch failed. Derived from ``ok``. */
  get failed(): boolean {
    return !this._ok;
  }

  get commandId(): string {
    return this._commandId;
  }

  /**
   * Success-only wire echo (MDI string, G-code diagnostic, …).
   * Empty string when no echo was returned. Never set on the failure
   * path.
   */
  get message(): string {
    return this._message;
  }

  /** ``string`` when failed, ``null`` on success. */
  get failureReason(): string | null {
    return this._failureReason;
  }

  /**
   * HTTP status from the underlying ``ApiError`` (``null`` on
   * network drops / native ``Error``s / success). Use this to log
   * or branch on the canonical error class (``statusCode ?? 0 >= 400``).
   */
  get statusCode(): number | null {
    return this._statusCode;
  }

  static success(params: CommandResultSuccessParams = {}): CommandResult {
    return new CommandResult({
      ok: true,
      commandId: params.commandId ?? "",
      message: params.message ?? "",
    });
  }

  static failure(
    reason: string | null,
    params: CommandResultFailureParams = {},
  ): CommandResult {
    return new CommandResult({
      ok: false,
      commandId: params.commandId ?? "",
      failureReason: reason,
      statusCode: params.statusCode ?? null,
    });
  }
}
