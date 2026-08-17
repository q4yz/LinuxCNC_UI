// JS port of ``backend/modules/macros/parser.py``. Splits a raw
// ``.macro`` text payload into an ordered list of alternating
// ``static`` (G-code) and ``python`` blocks delimited by ``{ ... }``.
//
// The state machine is intentionally identical to the backend so
// the two implementations cannot drift: same ``in_python`` /
// ``string_quote`` / ``escape_next`` flags, same whitelisted
// characters (``A–Z``, ``a–z``, ``0–9``, ``_``, ``-``, ``.``), same
// error message for an unclosed ``{``.
//
// Why port rather than call the backend?
//   * The parser is pure-Python and not exposed over HTTP yet.
//   * The dashboard "Run" feature needs block-by-block dispatch and
//     cannot tolerate a backend round-trip per block.
//   * The algorithm is small enough (~80 lines) that keeping two
//     in sync via the tests below is cheap; the regex boundaries
//     are easy to eyeball on either side.
//
// Whitespace semantics: leading / trailing whitespace on each block
// is stripped via the same ``String#strip()`` rule the backend uses,
// so the operator does not see the newline adjacent to a
// ``{``/``}`` delimiter in the block they actually receive.
//
// In addition to the parser, this module exposes a kind-aware
// validator (``validateMacroKindName``) so the dashboard and
// Machine Config panels can mirror the backend's
// ``backend/modules/macros/storage.py`` name policies without
// round-tripping. ``macro`` / ``ngc`` share the existing profile
// regex; ``mcode`` is the canonical LinuxCNC custom-M-code range
// M100..M199 (regex ``^M1\d{2}$``), matching
// ``MCodeFileService.MCODE_NAME`` on the backend.

export class MacroParseError extends Error {
  constructor(message) {
    super(message);
    this.name = 'MacroParseError';
  }
}

/**
 * Parse a ``.macro`` text payload into an ordered list of blocks.
 *
 * @param {string} source Raw ``.macro`` content as returned by the
 *   macros module's ``GET /api/v1/modules/macros/{name}``.
 * @returns {Array<{type: 'static'|'python', content: string}>}
 *   Empty input returns ``[]``. A source with no ``{`` returns a
 *   single-element list of one ``static`` block. A source that is
 *   just ``{}`` returns ``[{"type": "python", "content": ""}]``.
 * @throws {MacroParseError} If the source ends inside an unclosed
 *   ``{`` python block. The message reports the character offset of
 *   the opening brace that was never closed.
 */
export function parseMacro(source) {
  if (typeof source !== 'string') {
    throw new MacroParseError(
      `macro source must be a string, got ${typeof source}`,
    );
  }

  /** @type {Array<{type: 'static'|'python', content: string}>} */
  const blocks = [];

  let inPython = false;
  /** @type {null|'"'|"'"} */
  let stringQuote = null;
  let escapeNext = false;
  let openBraceOffset = null;
  /** @type {string[]} */
  const buffer = [];

  for (let offset = 0; offset < source.length; offset++) {
    const ch = source[offset];

    if (!inPython) {
      if (ch === '{') {
        const staticContent = buffer.join('').trim();
        if (staticContent) {
          blocks.push({ type: 'static', content: staticContent });
        }
        buffer.length = 0;
        inPython = true;
        stringQuote = null;
        escapeNext = false;
        openBraceOffset = offset;
        continue;
      }
      buffer.push(ch);
      continue;
    }

    // Python mode -------------------------------------------------
    if (escapeNext) {
      buffer.push(ch);
      escapeNext = false;
      continue;
    }

    if (ch === '\\') {
      buffer.push(ch);
      escapeNext = true;
      continue;
    }

    if (stringQuote !== null) {
      if (ch === stringQuote) stringQuote = null;
      buffer.push(ch);
      continue;
    }

    if (ch === '"' || ch === "'") {
      stringQuote = ch;
      buffer.push(ch);
      continue;
    }

    if (ch === '}') {
      const pythonContent = buffer.join('').trim();
      blocks.push({ type: 'python', content: pythonContent });
      buffer.length = 0;
      inPython = false;
      stringQuote = null;
      escapeNext = false;
      openBraceOffset = null;
      continue;
    }

    buffer.push(ch);
  }

  if (inPython) {
    throw new MacroParseError(
      `unclosed '{' in macro source at offset ${openBraceOffset}`,
    );
  }

  const trailing = buffer.join('').trim();
  if (trailing) {
    blocks.push({ type: 'static', content: trailing });
  }

  return blocks;
}

/**
 * Same rules as ``MacroStorage._validate`` on the backend. Used by
 * the management panel so a typo surfaces before the round-trip.
 *
 * @param {string} name
 * @returns {string} The trimmed name (unchanged on success).
 * @throws {Error} When the name fails the regex.
 */
export function validateMacroName(name) {
  if (typeof name !== 'string' || name === '' || name === '.' || name === '..') {
    throw new Error(`invalid macro name: ${JSON.stringify(name)}`);
  }
  if (!/^[A-Za-z0-9._-]{1,64}$/.test(name)) {
    throw new Error(
      `invalid macro name: ${JSON.stringify(name)} (must match ^[A-Za-z0-9._-]{1,64}$)`,
    );
  }
  return name;
}

/**
 * Regex for valid M-code names. Mirrors
 * ``MCodeFileService.MCODE_NAME`` on the backend — M100..M199
 * inclusive (so ``M1\d{2}`` covers the entire range; the regex
 * matches exactly 4 characters: ``M`` followed by ``1`` and two
 * digits).
 */
export const MCODE_NAME_REGEX = /^M1\d{2}$/;

/**
 * Kind-aware name validator. ``macro`` and ``ngc`` use the existing
 * ``^[A-Za-z0-9._-]{1,64}$`` regex (same as
 * ``MacroStorage._validate``); ``mcode`` uses the canonical LinuxCNC
 * range M100..M199 (``^M1\d{2}$``). Out-of-range names throw so the
 * UI surfaces the same error the backend would.
 *
 * @param {"macro"|"ngc"|"mcode"} kind
 * @param {string} name
 * @returns {string} The trimmed name (unchanged on success).
 */
export function validateMacroKindName(kind, name) {
  if (kind === 'mcode') {
    if (!MCODE_NAME_REGEX.test(name)) {
      throw new Error(
        `invalid M-code name: ${JSON.stringify(name)} ` +
        '(must match ^M1\\d{2}$ — i.e. M100..M199)',
      );
    }
    return name;
  }
  // macro / ngc share the legacy regex.
  return validateMacroName(name);
}

export default parseMacro;
