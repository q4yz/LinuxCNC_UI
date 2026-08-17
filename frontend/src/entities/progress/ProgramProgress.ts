// Program-progress entity. Mirrors the `ProgramProgressResponse`
// Pydantic shape on the backend.

export enum InterpState {
  ERROR = -1,
  NOT_LOADED = 0,
  IDLE = 1,
  READING = 2,
  PAUSED = 3,
  WAITING = 4,
}

// Kept for backward compatibility with JS consumers during the migration
export const INTERP_STATES = {
  IDLE: InterpState.IDLE,
  READING: InterpState.READING,
  PAUSED: InterpState.PAUSED,
  WAITING: InterpState.WAITING,
  ERROR: InterpState.ERROR,
  NOT_LOADED: InterpState.NOT_LOADED,
} as const;

export interface ProgramProgressParams {
  currentLine?: number;
  motionLine?: number;
  totalLines?: number;
  file?: string;
  interpState?: number;
}

export class ProgramProgress {
  private readonly _currentLine: number;
  private readonly _motionLine: number;
  private readonly _totalLines: number;
  private readonly _file: string;
  private readonly _interpState: number;

  constructor({
    currentLine = 0,
    motionLine = 0,
    totalLines = 0,
    file = "",
    interpState = InterpState.IDLE,
  }: ProgramProgressParams = {}) {
    this._currentLine = Number.isFinite(currentLine) ? Math.max(0, currentLine) : 0;
    this._motionLine = Number.isFinite(motionLine) ? Math.max(0, motionLine) : 0;
    this._totalLines = Number.isFinite(totalLines) ? Math.max(0, totalLines) : 0;
    this._file = typeof file === "string" ? file : "";
    this._interpState = Number.isFinite(interpState) ? interpState : InterpState.IDLE;
  }

  get currentLine(): number {
    return this._currentLine;
  }

  get motionLine(): number {
    return this._motionLine;
  }

  get totalLines(): number {
    return this._totalLines;
  }

  get file(): string {
    return this._file;
  }

  get interpState(): number {
    return this._interpState;
  }

  /** Fraction of total lines already executed (0..100). */
  get fraction(): number {
    if (this._totalLines <= 0) return 0;
    if (this._currentLine < 0) return 0;
    return Math.min(100, (this._currentLine / this._totalLines) * 100);
  }

  get isLoaded(): boolean {
    return this._file.length > 0;
  }

  get isRunning(): boolean {
    // InterpState.READING == 2 in the backend.
    return this._interpState === InterpState.READING;
  }

  get isPaused(): boolean {
    return this._interpState === InterpState.PAUSED;
  }

  get isIdle(): boolean {
    return this._interpState === InterpState.IDLE || this._interpState === InterpState.NOT_LOADED;
  }
}