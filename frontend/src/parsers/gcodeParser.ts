// LinuxCNC-aware NGC / G-code toolpath parser.
//
// Pure ``string -> ParsedSegment[]`` — no DOM, no Three.js, no
// filesystem. The Vue viewer consumes this; the existing
// ``macrosParser.ts`` precedent uses the same shape.
//
// What is implemented
// -------------------
//
// Modal groups (sticky across lines):
//   * Motion (1 / 2 / 3 — G1, G2, G3). G0 is non-modal: it emits a
//     rapid segment but does not change the modal group, matching
//     RS274/NGC. G80 cancels.
//   * Plane (G17 / G18 / G19 — XY / XZ / YZ).
//   * Distance mode (G90 / G91 — absolute / incremental).
//   * Arc centre mode (G90.1 / G91.1 — absolute / incremental from
//     start; default G91.1, matching LinuxCNC).
//   * WCS (G54..G59.3 — indices 1..9).
//   * G92 family: G92 (set per axis), G92.1 (clear all), G92.2
//     (suspend), G92.3 (resume).
//
// Motion
//   * G2 / G3 are interpolated as proper arcs in the active plane
//     using I/J/K offsets (or R-word radius). I/J/K offsets follow
//     the axis letter: I↔X, J↔Y, K↔Z. The third axis is linearly
//     interpolated when the user specifies it on the same line,
//     giving free helical-arc support.
//   * Lines that omit the G-code use the current modal motion. A
//     permissive G1 default applies before any modal motion is
//     established so a stray ``X10`` still produces a segment.
//
// What is NOT implemented (out of scope for this refactor)
// --------------------------------------------------------
//   * Subroutines (O-words, M98 / M99).
//   * Cutter compensation (G41 / G42 with D-word).
//   * Tool length offset (G43 / G49).
//   * G28 / G30 intermediate-point handling (still emitted as a
//     single straight segment).
//   * Parametric expressions (``#var``).
//   * Units rescaling (G20 / G21 are tracked but ignored).
//
// These can be added behind the same entry point without touching
// the viewer.
//
// Comment handling
// ----------------
//   * Strip from the first ``;`` to EOL.
//   * Strip parenthesised ``( ... )`` comments. Balanced nesting is
//     walked character-by-character; unbalanced parentheses fall
//     back to a non-greedy regex strip so the rest of the line
//     still tokenises.

import { WORK_COORDINATE_SYSTEMS } from '../config/gcodes'

/**
 * One motion segment with the per-line parser state captured at the
 * moment it was emitted. ``wcsIndex`` is 1..9 (G54..G59.3);
 * ``g92`` is the additive offset that was active when the line was
 * parsed (zeroed if a G92.2 suspension was in effect).
 * ``sourceLine`` is the 1-based index of the file line that
 * produced this segment — the renderer uses it to colour already
 * cut segments via the live ``motionLine`` from telemetry.
 */
export interface ParsedSegment {
  from: [number, number, number]
  to:   [number, number, number]
  wcsIndex: number
  g92:    [number, number, number]
  sourceLine: number
}

export interface GcodeParserOptions {
  /**
   * Maximum straight-line distance between consecutive points when
   * rasterising a G2 / G3 arc. Smaller = smoother but more vertices.
   * Default 1.0 (assumed mm — same unit space as the file).
   */
  arcChordTolerance?: number
  /** Hard cap on segments emitted per arc. Default 256. */
  arcMaxSegments?: number
  /** Plane active before any explicit G17 / G18 / G19. Default G17. */
  initialPlane?: 'G17' | 'G18' | 'G19'
  /** Arc-centre mode before any explicit G90.1 / G91.1. Default G91.1. */
  initialArcCenterMode?: 'G90.1' | 'G91.1'
}

const DEFAULT_ARC_CHORD_TOLERANCE = 1.0
const DEFAULT_ARC_MAX_SEGMENTS = 256

type Plane = 'G17' | 'G18' | 'G19'
type ArcCenterMode = 'G90.1' | 'G91.1'
type ModalMotion = 1 | 2 | 3 | null

const PLANE_AXES: Record<Plane, { a: 'X' | 'Y' | 'Z'; b: 'X' | 'Y' | 'Z' }> = {
  G17: { a: 'X', b: 'Y' },
  G18: { a: 'X', b: 'Z' },
  G19: { a: 'Y', b: 'Z' },
}

const ALL_AXES = ['X', 'Y', 'Z'] as const
type Axis = (typeof ALL_AXES)[number]

interface Vec3 { x: number; y: number; z: number }

const vec3 = (x: number, y: number, z: number): Vec3 => ({ x, y, z })

const axVal = (v: Vec3, ax: Axis): number => {
  if (ax === 'X') return v.x
  if (ax === 'Y') return v.y
  return v.z
}

const setAx = (v: Vec3, ax: Axis, val: number): Vec3 => {
  if (ax === 'X') return { ...v, x: val }
  if (ax === 'Y') return { ...v, y: val }
  return { ...v, z: val }
}

const outOfPlaneAxis = (plane: Plane): Axis => {
  const { a, b } = PLANE_AXES[plane]
  return ALL_AXES.find((ax) => ax !== a && ax !== b) ?? 'Z'
}

/**
 * Look up the canonical WCS name (G54, G55, … G59.3) for a 1-based
 * index. Falls back to ``G54`` for out-of-range values so a stale
 * telemetry field cannot produce an undefined overlay string.
 */
export const wcsNameForIndex = (idx: number): string => {
  const sys = WORK_COORDINATE_SYSTEMS.find((s) => s.index === idx)
  return sys ? sys.name : 'G54'
}

const gwordToWcsIndex = (value: number): number | null => {
  if (!Number.isFinite(value)) return null
  if (value >= 54 && value <= 59) return Math.floor(value) - 53
  if (Math.abs(value - 59.1) < 1e-9) return 7
  if (Math.abs(value - 59.2) < 1e-9) return 8
  if (Math.abs(value - 59.3) < 1e-9) return 9
  return null
}

/**
 * Strip ``;…EOL`` and parenthesised comments. If parentheses are
 * unbalanced we keep the line and apply a non-greedy regex strip so
 * the rest of the G-code outside the unmatched section still parses
 * (matches LinuxCNC's tolerance).
 */
const stripComments = (line: string): string => {
  let s = line
  const semi = s.indexOf(';')
  if (semi >= 0) s = s.slice(0, semi)

  let opens = 0
  let closes = 0
  for (const ch of s) {
    if (ch === '(') opens++
    else if (ch === ')') closes++
  }
  if (opens !== closes) {
    return s.replace(/\(.*?\)/g, '').trim()
  }

  let out = ''
  let depth = 0
  for (const ch of s) {
    if (ch === '(') { depth++; continue }
    if (ch === ')') { if (depth > 0) depth--; continue }
    if (depth === 0) out += ch
  }
  return out.trim()
}

const tokenize = (line: string): string[] =>
  line.split(/\s+/).filter((t) => t.length > 0)

interface Token {
  letter: string
  value: number
}

const parseToken = (token: string): Token | null => {
  if (!token) return null
  const letter = token[0].toUpperCase()
  const rest = token.slice(1)
  const value = Number(rest)
  if (!Number.isFinite(value)) return null
  return { letter, value }
}

const signOf = (n: number): number =>
  n > 1e-12 ? 1 : n < -1e-12 ? -1 : 0

interface ArcChord {
  from: Vec3
  to: Vec3
}

/**
 * Rasterise one G2 / G3 arc into a sequence of straight chords.
 * Out-of-plane axis is interpolated linearly when ``helical`` is
 * true (Z word given alongside a G17 arc, etc.); otherwise it
 * stays at the start value.
 */
const interpolateArc = (
  start: Vec3,
  end: Vec3,
  center: Vec3,
  cw: boolean,
  plane: Plane,
  helical: boolean,
  chordTol: number,
  maxSegs: number,
): ArcChord[] => {
  const { a, b } = PLANE_AXES[plane]
  const oop = outOfPlaneAxis(plane)
  const startA = axVal(start, a)
  const startB = axVal(start, b)
  const endA = axVal(end, a)
  const endB = axVal(end, b)
  const cA = axVal(center, a)
  const cB = axVal(center, b)
  const radius = Math.hypot(startA - cA, startB - cB)
  if (radius < 1e-9) {
    return [{ from: start, to: end }]
  }

  const a0 = Math.atan2(startB - cB, startA - cA)
  const aE = Math.atan2(endB - cB, endA - cA)

  // Unwrap to the sweep that matches the requested direction. CCW
  // (G3) is positive in standard math, CW (G2) is negative. The
  // atan2 result lands in (-π, π] so a "wrong way" sweep needs a
  // 2π flip.
  let sweep = aE - a0
  while (sweep <= -Math.PI) sweep += 2 * Math.PI
  while (sweep > Math.PI) sweep -= 2 * Math.PI
  if (!cw && sweep <= 0) sweep += 2 * Math.PI
  if (cw && sweep >= 0) sweep -= 2 * Math.PI

  const arcLen = Math.abs(sweep) * radius
  const segsByLen = Math.ceil(arcLen / Math.max(chordTol, 1e-6))
  const count = Math.max(1, Math.min(maxSegs, segsByLen))

  const out: ArcChord[] = []
  let prev = start
  const sOop = axVal(start, oop)
  const eOop = axVal(end, oop)
  for (let i = 1; i <= count; i++) {
    const t = i / count
    const ang = a0 + sweep * t
    let pt = vec3(0, 0, 0)
    pt = setAx(pt, a, cA + radius * Math.cos(ang))
    pt = setAx(pt, b, cB + radius * Math.sin(ang))
    if (helical) {
      pt = setAx(pt, oop, sOop + (eOop - sOop) * t)
    } else {
      pt = setAx(pt, oop, sOop)
    }
    out.push({ from: prev, to: pt })
    prev = pt
  }
  return out
}

/**
 * Parse a complete NGC / G-code program into an ordered list of
 * motion segments. Each G-code line that emits a move contributes
 * one or more entries: G0 / G1 contribute one straight segment;
 * G2 / G3 contribute N straight chords approximating the arc.
 *
 * The parser is permissive — lines that contain only modal G-codes
 * (e.g. ``G90`` alone) update state but emit no segment. Lines with
 * unrecognised tokens (M-codes, F-words, S-words, …) are skipped.
 */
export const parseGcodeToolpath = (
  text: string,
  options: GcodeParserOptions = {},
): ParsedSegment[] => {
  const segments: ParsedSegment[] = []

  let motion: ModalMotion = null
  let absolute = true
  let plane: Plane = options.initialPlane ?? 'G17'
  let arcCenterMode: ArcCenterMode = options.initialArcCenterMode ?? 'G91.1'
  let activeWcs = 1
  const g92: [number, number, number] = [0, 0, 0]
  const g92Snapshot: [number, number, number] = [0, 0, 0]
  let g92Suspended = false
  let pendingG92: 'set' | 'clear' | 'suspend' | 'resume' | null = null

  let curX = 0
  let curY = 0
  let curZ = 0
  let hasPosition = false

  const chordTol = options.arcChordTolerance ?? DEFAULT_ARC_CHORD_TOLERANCE
  const maxSegs = options.arcMaxSegments ?? DEFAULT_ARC_MAX_SEGMENTS

  const lines = text.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    if (raw === undefined) continue

    const cleaned = stripComments(raw)
    if (!cleaned) continue

    const tokens = tokenize(cleaned)
    const parsedTokens: Token[] = []
    for (const tk of tokens) {
      const p = parseToken(tk)
      if (p) parsedTokens.push(p)
    }

    let newX: number | null = null
    let newY: number | null = null
    let newZ: number | null = null
    let lineMotion: ModalMotion = null
    let lineRapid = false
    let iVal: number | null = null
    let jVal: number | null = null
    let kVal: number | null = null
    let hasR = false
    let rValue = 0
    pendingG92 = null

    for (const { letter, value } of parsedTokens) {
      switch (letter) {
        case 'G': {
          const wcs = gwordToWcsIndex(value)
          if (wcs !== null) {
            activeWcs = wcs
            break
          }
          if (value === 0) lineRapid = true
          else if (value === 1) lineMotion = 1
          else if (value === 2) lineMotion = 2
          else if (value === 3) lineMotion = 3
          else if (value === 17) plane = 'G17'
          else if (value === 18) plane = 'G18'
          else if (value === 19) plane = 'G19'
          else if (value === 80) motion = null
          else if (Math.abs(value - 90.1) < 1e-9) arcCenterMode = 'G90.1'
          else if (Math.abs(value - 90) < 1e-9) absolute = true
          else if (Math.abs(value - 91.1) < 1e-9) arcCenterMode = 'G91.1'
          else if (Math.abs(value - 91) < 1e-9) absolute = false
          else if (value === 92) {
            pendingG92 = 'set'
            g92Suspended = false
          } else if (Math.abs(value - 92.1) < 1e-9) pendingG92 = 'clear'
          else if (Math.abs(value - 92.2) < 1e-9) pendingG92 = 'suspend'
          else if (Math.abs(value - 92.3) < 1e-9) pendingG92 = 'resume'
          break
        }
        case 'X':
          newX = absolute || !hasPosition ? value : curX + value
          break
        case 'Y':
          newY = absolute || !hasPosition ? value : curY + value
          break
        case 'Z':
          newZ = absolute || !hasPosition ? value : curZ + value
          break
        case 'I': iVal = value; break
        case 'J': jVal = value; break
        case 'K': kVal = value; break
        case 'R':
          hasR = true
          rValue = value
          break
      }
    }

    // Resolve the G92 family. ``G92 X.. Y.. Z..`` only touches the
    // axes it explicitly mentions — omitted axes keep their current
    // value. ``G92.1`` zeros everything, ``G92.2`` suspends (G92
    // contribution becomes 0 until G92.3 resumes it), ``G92.3``
    // restores the snapshot taken at suspend time. G92 lines never
    // produce a motion segment regardless of axis words.
    if (pendingG92) {
      if (pendingG92 === 'set') {
        for (const { letter, value } of parsedTokens) {
          if (letter === 'X') g92[0] = value
          else if (letter === 'Y') g92[1] = value
          else if (letter === 'Z') g92[2] = value
        }
      } else if (pendingG92 === 'clear') {
        g92[0] = 0; g92[1] = 0; g92[2] = 0
        g92Snapshot[0] = 0; g92Snapshot[1] = 0; g92Snapshot[2] = 0
        g92Suspended = false
      } else if (pendingG92 === 'suspend') {
        g92Snapshot[0] = g92[0]
        g92Snapshot[1] = g92[1]
        g92Snapshot[2] = g92[2]
        g92Suspended = true
      } else if (pendingG92 === 'resume') {
        g92[0] = g92Snapshot[0]
        g92[1] = g92Snapshot[1]
        g92[2] = g92Snapshot[2]
        g92Suspended = false
      }
      pendingG92 = null
      continue
    }

    // Determine the motion for this line. G0 is non-modal: it does
    // not change ``motion`` but the segment is still emitted as a
    // straight rapid. G1/G2/G3 update ``motion``; absent G-code
    // reuses the current modal motion (default G1).
    let effectiveMotion: ModalMotion
    if (lineRapid) {
      effectiveMotion = null
    } else if (lineMotion !== null) {
      motion = lineMotion
      effectiveMotion = lineMotion
    } else {
      effectiveMotion = motion ?? 1
    }

    if (newX === null && newY === null && newZ === null) {
      // No axis words: G2/G3 with I/J/K (or R) but no X/Y/Z draws
      // a full circle back to the current position. Anything else
      // (a pure modal-state line) emits no segment.
      const hasArcCentre =
        iVal !== null || jVal !== null || kVal !== null || hasR
      const isArc = effectiveMotion === 2 || effectiveMotion === 3
      if (!isArc || !hasArcCentre) continue
      // prev = cur; fall through with newX/Y/Z all null so cur is
      // not updated.
    }

    const prevX = curX
    const prevY = curY
    const prevZ = curZ
    if (newX !== null) curX = newX
    if (newY !== null) curY = newY
    if (newZ !== null) curZ = newZ

    // The first motion line still produces a segment from the
    // initial position (0, 0, 0). Skipping it would hide the
    // toolpath's first move in the preview, which matters for any
    // program whose first G-code is a real rapid/feed.
    hasPosition = true

    // While G92.2 is in effect, the G92 contribution is zero.
    const effectiveG92: [number, number, number] = g92Suspended
      ? [0, 0, 0]
      : [g92[0], g92[1], g92[2]]

    if (effectiveMotion === 2 || effectiveMotion === 3) {
      const cw = effectiveMotion === 2
      const start: Vec3 = vec3(prevX, prevY, prevZ)
      const end: Vec3 = vec3(curX, curY, curZ)
      const { a, b } = PLANE_AXES[plane]
      const oop = outOfPlaneAxis(plane)
      const helical =
        (oop === 'X' && newX !== null) ||
        (oop === 'Y' && newY !== null) ||
        (oop === 'Z' && newZ !== null)

      const startA = axVal(start, a)
      const startB = axVal(start, b)
      const endA = axVal(end, a)
      const endB = axVal(end, b)

      let center: Vec3

      if (hasR) {
        // R-word: pick the centre on the side of the chord that
        // matches the requested sweep direction.
        const dx = endA - startA
        const dy = endB - startB
        const chordLen = Math.hypot(dx, dy)
        if (chordLen < 1e-9 || Math.abs(rValue) * 2 < chordLen - 1e-9) {
          // Degenerate chord or R too small to span it.
          segments.push({
            from: [prevX, prevY, prevZ],
            to: [curX, curY, curZ],
            wcsIndex: activeWcs,
            g92: effectiveG92,
            sourceLine: i + 1,
          })
          continue
        }
        const halfChord = chordLen / 2
        const h = Math.sqrt(
          Math.max(0, rValue * rValue - halfChord * halfChord),
        )
        const mx = (startA + endA) / 2
        const my = (startB + endB) / 2
        // Perpendicular unit vector (rotated 90° CCW in the plane).
        const perpX = -dy / chordLen
        const perpY = dx / chordLen
        const c1A = mx + perpX * h
        const c1B = my + perpY * h
        const c2A = mx - perpX * h
        const c2B = my - perpY * h

        const wantedSign = cw ? -1 : 1
        const s1 = Math.atan2(endB - c1B, endA - c1A)
              - Math.atan2(startB - c1B, startA - c1A)
        const s2 = Math.atan2(endB - c2B, endA - c2A)
              - Math.atan2(startB - c2B, startA - c2A)
        // Normalise to (-π, π].
        const norm = (s: number): number => {
          let v = s
          while (v <= -Math.PI) v += 2 * Math.PI
          while (v > Math.PI) v -= 2 * Math.PI
          return v
        }
        const n1 = norm(s1)
        const n2 = norm(s2)
        const m1 = signOf(n1) === wantedSign
        const m2 = signOf(n2) === wantedSign
        let chosenA: number
        let chosenB: number
        if (m1 && !m2) { chosenA = c1A; chosenB = c1B }
        else if (m2 && !m1) { chosenA = c2A; chosenB = c2B }
        else if (m1 && m2) {
          // Both centres match (rare, only when sweep ≈ 0). Pick
          // the smaller absolute sweep.
          chosenA = Math.abs(n1) <= Math.abs(n2) ? c1A : c2A
          chosenB = Math.abs(n1) <= Math.abs(n2) ? c1B : c2B
        } else {
          // Neither matches — fall back to a straight segment.
          segments.push({
            from: [prevX, prevY, prevZ],
            to: [curX, curY, curZ],
            wcsIndex: activeWcs,
            g92: effectiveG92,
            sourceLine: i + 1,
          })
          continue
        }

        center = setAx(setAx(vec3(0, 0, 0), a, chosenA), b, chosenB)
        center = setAx(center, oop, axVal(start, oop))
      } else {
        // I / J / K offsets. Each offset letter maps to an axis;
        // the active plane picks which two we use.
        const offsetA = a === 'X' ? (iVal ?? 0)
                      : a === 'Y' ? (jVal ?? 0)
                      :             (kVal ?? 0)
        const offsetB = b === 'X' ? (iVal ?? 0)
                      : b === 'Y' ? (jVal ?? 0)
                      :             (kVal ?? 0)
        let cA: number
        let cB: number
        if (arcCenterMode === 'G91.1') {
          cA = startA + offsetA
          cB = startB + offsetB
        } else {
          cA = offsetA
          cB = offsetB
        }
        center = setAx(setAx(vec3(0, 0, 0), a, cA), b, cB)
        center = setAx(center, oop, axVal(start, oop))
      }

      const arcSegs = interpolateArc(
        start, end, center, cw, plane, helical, chordTol, maxSegs,
      )
      for (const seg of arcSegs) {
        segments.push({
          from: [seg.from.x, seg.from.y, seg.from.z],
          to:   [seg.to.x,   seg.to.y,   seg.to.z],
          wcsIndex: activeWcs,
          g92: effectiveG92,
          sourceLine: i + 1,
        })
      }
    } else {
      segments.push({
        from: [prevX, prevY, prevZ],
        to:   [curX,  curY,  curZ],
        wcsIndex: activeWcs,
        g92: effectiveG92,
        sourceLine: i + 1,
      })
    }
  }

  return segments
}

export default parseGcodeToolpath