/** One ``samples`` frame of ``/ws/hal-scope``: per sample its time ``t``
 * (s) and one value per pin (``null``: not readable). ``missed``: samples
 * the backend dropped since the last frame. */
export interface ScopeFrame {
  pins: string[];
  t: number[];
  v: (number | null)[][];
  missed?: number;
}
