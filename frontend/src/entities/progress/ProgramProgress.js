// Program-progress entity. Mirrors the ``ProgramProgressResponse``
// Pydantic shape on the backend: ``current_line`` / ``motion_line``
// / ``total_lines`` / ``file`` / ``interp_state``. The
// ``fraction`` getter is the canonical "what fraction of the
// program is complete" view the dashboard widgets consume.

export const INTERP_STATES = Object.freeze({
  IDLE: 1,
  READING: 2,
  PAUSED: 3,
  WAITING: 4,
  ERROR: -1,
  // The backend also reports 0 for "not loaded" — expose a friendly
  // sentinel for that case.
  NOT_LOADED: 0,
});

export class ProgramProgress {
  /**
   * @param {object} params
   * @param {number} [params.currentLine]
   * @param {number} [params.motionLine]
   * @param {number} [params.totalLines]
   * @param {string} [params.file]
   * @param {number} [params.interpState]
   */
  constructor({
    currentLine = 0,
    motionLine = 0,
    totalLines = 0,
    file = "",
    interpState = INTERP_STATES.IDLE,
  } = {}) {
    this._currentLine = Number.isFinite(currentLine) ? Math.max(0, currentLine) : 0;
    this._motionLine = Number.isFinite(motionLine) ? Math.max(0, motionLine) : 0;
    this._totalLines = Number.isFinite(totalLines) ? Math.max(0, totalLines) : 0;
    this._file = typeof file === "string" ? file : "";
    this._interpState = Number.isFinite(interpState) ? interpState : INTERP_STATES.IDLE;
  }

  get currentLine() {
    return this._currentLine;
  }

  get motionLine() {
    return this._motionLine;
  }

  get totalLines() {
    return this._totalLines;
  }

  get file() {
    return this._file;
  }

  get interpState() {
    return this._interpState;
  }

  /** Fraction of total lines already executed (0..100). */
  get fraction() {
    if (this._totalLines <= 0) return 0;
    if (this._currentLine < 0) return 0;
    return Math.min(100, (this._currentLine / this._totalLines) * 100);
  }

  get isLoaded() {
    return this._file.length > 0;
  }

  get isRunning() {
    // INTERP_STATES.READING == 2 in the backend.
    return this._interpState === INTERP_STATES.READING;
  }

  get isPaused() {
    return this._interpState === INTERP_STATES.PAUSED;
  }

  get isIdle() {
    return this._interpState === INTERP_STATES.IDLE || this._interpState === INTERP_STATES.NOT_LOADED;
  }
}
