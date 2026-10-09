// Progress of the last system update — written by `scripts/update.sh`,
// served by `GET /api/v1/system/update/status`. "done" is only written
// after the restarted services answered, so the UI may reload on it.

export type UpdateState = "idle" | "running" | "done" | "failed";

export interface UpdateStatusParams {
  runId?: string | null;
  state?: UpdateState;
  phase?: string;
  message?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  commitBefore?: string | null;
  commitAfter?: string | null;
  logTail?: string;
}

export class UpdateStatus {
  private readonly _runId: string | null;
  private readonly _state: UpdateState;
  private readonly _phase: string;
  private readonly _message: string;
  private readonly _startedAt: string | null;
  private readonly _finishedAt: string | null;
  private readonly _commitBefore: string | null;
  private readonly _commitAfter: string | null;
  private readonly _logTail: string;

  constructor({
    runId = null,
    state = "idle",
    phase = "",
    message = "",
    startedAt = null,
    finishedAt = null,
    commitBefore = null,
    commitAfter = null,
    logTail = "",
  }: UpdateStatusParams = {}) {
    this._runId = runId || null;
    this._state = state;
    this._phase = phase;
    this._message = message;
    this._startedAt = startedAt || null;
    this._finishedAt = finishedAt || null;
    this._commitBefore = commitBefore || null;
    this._commitAfter = commitAfter || null;
    this._logTail = logTail;
  }

  get runId(): string | null {
    return this._runId;
  }

  get state(): UpdateState {
    return this._state;
  }

  get phase(): string {
    return this._phase;
  }

  get message(): string {
    return this._message;
  }

  get startedAt(): string | null {
    return this._startedAt;
  }

  get finishedAt(): string | null {
    return this._finishedAt;
  }

  /** Epoch ms of `finishedAt`, 0 when unknown. */
  get finishedAtMs(): number {
    const ms = this._finishedAt ? Date.parse(this._finishedAt) : NaN;
    return Number.isFinite(ms) ? ms : 0;
  }

  get commitBefore(): string | null {
    return this._commitBefore;
  }

  get commitAfter(): string | null {
    return this._commitAfter;
  }

  /** Last lines of `update.log` — failed runs only. */
  get logTail(): string {
    return this._logTail;
  }

  get isRunning(): boolean {
    return this._state === "running";
  }

  get isFinished(): boolean {
    return this._state === "done" || this._state === "failed";
  }
}
