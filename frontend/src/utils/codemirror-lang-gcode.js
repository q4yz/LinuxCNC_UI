// G-code (RS-274 / LinuxCNC) language pack for CodeMirror 6.
// Built on top of the shared ``simpleMode`` factory from
// ``@codemirror/legacy-modes`` so we get a clean state-machine
// lexer without hand-rolling the boilerplate.
//
// Token buckets (each regex is matched against the current stream
// position in declaration order — first match wins):
//
//   ; ...                 -> comment                  (full-line comment)
//   G<digits> / M<digits> -> keyword + number         (preparatory / misc)
//   N<digits>             -> meta + number            (line number)
//   O<digits>             -> def + number             (subprogram label)
//   T<digits>             -> keyword + number         (tool select)
//   F<digits> / S<digits> -> attributeName + number  (feed / spindle)
//   <axis X Y Z A B C U V W I J K R P Q L><digits> -> propertyName + number
//
// Anything that does not match is left uncoloured (whitespace,
// ``%`` program delimiters, parentheses-style messages, etc.).
//
// References:
//   - LinuxCNC G-code reference: https://linuxcnc.org/docs/html/gcode/
//   - RS-274: starts each word with a letter, optionally followed by
//     a signed decimal value; ``;`` starts a comment to EOL.

import { StreamLanguage } from '@codemirror/language'
import { simpleMode } from '@codemirror/legacy-modes/mode/simple-mode'

// Motion / miscellaneous verb codes (G, M).
const VERB_RE = /^([GM])\s*(-?\d+(?:\.\d+)?)/i
// Block line number.
const LINE_NUMBER_RE = /^(N)(\d+)/i
// Subprogram / subroutine label.
const SUB_RE = /^(O)(\d+)/i
// Tool selection.
const TOOL_RE = /^(T)(\d+)/i
// Feed rate / spindle speed.
const SPINDLE_FEED_RE = /^([FS])\s*(-?\d+(?:\.\d+)?)/i
// Axis / arc / parameter words. Includes I, J, K, R for arc centres;
// P, L, Q for dwells / repeat counts.
const AXIS_RE = /^([XYZABCUVWIJKRPQL])\s*(-?\d+(?:\.\d+)?)/i

export const gcode = () =>
  StreamLanguage.define(
    simpleMode({
      start: [
        // Full-line ``;`` comment. Matches first so the rest of the
        // line is never tokenised as parameters.
        { regex: /^;.*$/, sol: true, token: 'comment' },
        // Inline ``;`` comment after a word, e.g. ``G1 X10 ; move``.
        { regex: /\s*;.*$/, token: 'comment' },
        // Whitespace — advance the stream, no token.
        { regex: /\s+/, token: null },
        // Worded codes (verb > line-number > sub-label > tool > rate
        // > axis). The letter and the number are emitted as separate
        // token tags so the theme can colour them independently.
        { regex: VERB_RE, token: ['keyword', 'number'] },
        { regex: LINE_NUMBER_RE, token: ['meta', 'number'] },
        { regex: SUB_RE, token: ['def', 'number'] },
        { regex: TOOL_RE, token: ['keyword', 'number'] },
        { regex: SPINDLE_FEED_RE, token: ['attributeName', 'number'] },
        { regex: AXIS_RE, token: ['propertyName', 'number'] },
        // Anything else (e.g. ``%``, ``(msg,...)``): consume one char
        // so the lexer never loops forever on an unrecognised byte.
        { regex: /./, token: null },
      ],
      languageData: {
        commentTokens: { line: ';' },
        name: 'gcode',
      },
    })
  )
