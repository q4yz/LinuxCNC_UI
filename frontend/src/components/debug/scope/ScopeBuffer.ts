// Sample store for the HAL oscilloscope. Fed by `/ws/hal-scope` frames
// ({ pins, t: seconds, v: [[values of pin 0], ...] }); keeps the last
// `maxSeconds` of data. Plain arrays, trimmed in chunks (amortised O(1))
// — never reactive: the canvas reads it every animation frame and Vue
// proxies would cost more than the drawing.

export interface ScopeFrame {
  pins: string[];
  t: number[];
  v: (number | null)[][];
  missed?: number;
}

export class ScopeBuffer {
  readonly maxSeconds: number;
  private _pins: string[] = [];
  private _times: number[] = [];
  private _values = new Map<string, (number | null)[]>();
  private _missed = 0;

  constructor(maxSeconds = 60) {
    this.maxSeconds = maxSeconds;
  }

  /** Start over for a new pin set (a reconfigured stream restarts its clock). */
  reset(pins: string[]): void {
    this._pins = [...pins];
    this._times = [];
    this._values = new Map(pins.map((pin) => [pin, []]));
    this._missed = 0;
  }

  append(frame: ScopeFrame): void {
    if (!sameList(frame.pins, this._pins)) this.reset(frame.pins);
    const { t, v } = frame;
    // A restarted sampler restarts at t≈0: drop the old timeline.
    if (this._times.length && t.length && t[0] < this._times[this._times.length - 1]) this.reset(frame.pins);
    for (let i = 0; i < t.length; i++) this._times.push(t[i]);
    frame.pins.forEach((pin, column) => {
      const target = this._values.get(pin)!;
      const source = v[column] ?? [];
      for (let i = 0; i < t.length; i++) target.push(source[i] ?? null);
    });
    this._missed += frame.missed ?? 0;
    this.trim();
  }

  private trim(): void {
    const latest = this.latestTime;
    if (latest === null) return;
    const cut = lowerBound(this._times, latest - this.maxSeconds);
    // Trim in chunks so append stays amortised O(1).
    if (cut > 4096 || cut > this._times.length / 2) {
      this._times.splice(0, cut);
      for (const column of this._values.values()) column.splice(0, cut);
    }
  }

  get pins(): readonly string[] {
    return this._pins;
  }

  get times(): readonly number[] {
    return this._times;
  }

  values(pin: string): readonly (number | null)[] {
    return this._values.get(pin) ?? [];
  }

  get length(): number {
    return this._times.length;
  }

  get latestTime(): number | null {
    return this._times.length ? this._times[this._times.length - 1] : null;
  }

  /** Samples the backend could not take in time (busy CPU). */
  get missed(): number {
    return this._missed;
  }

  /** Samples per second actually received over the last `seconds`. */
  effectiveRate(seconds = 1): number {
    const latest = this.latestTime;
    if (latest === null) return 0;
    const from = lowerBound(this._times, latest - seconds);
    const span = latest - this._times[from];
    return span > 0 ? (this._times.length - 1 - from) / span : 0;
  }
}

/** First index whose value is >= `x` (`times` ascending). */
export function lowerBound(times: readonly number[], x: number): number {
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (times[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}
