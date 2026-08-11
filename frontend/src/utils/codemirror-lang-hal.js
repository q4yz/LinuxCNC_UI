// HAL (LinuxCNC Hardware Abstraction Layer) language pack for
// CodeMirror 6. Built on top of the shared ``clike`` StreamLanguage
// from ``@codemirror/legacy-modes`` so C-style line (``//``) and
// block (``/* ... */``) comments, strings and numbers are handled
// for free. Only the keyword set is HAL-specific.
//
// HAL syntax reference (LinuxCNC docs):
//   - ``loadusr`` / ``loadrt`` / ``unloadusr`` / ``unloadrt`` — load components
//   - ``addf`` / ``delf``                     — add/remove a function from a thread
//   - ``setp`` / ``sets``                     — set pin / signal value
//   - ``newsig`` / ``delsig``                 — create / delete a signal
//   - ``linkps`` / ``links`` / ``unlinkp``     — connect / disconnect pins & signals
//   - ``net``                                 — shorthand for ``newsig`` + ``links``
//   - ``show`` / ``comp``                     — introspection blocks
//
// Atoms are the boolean-ish literals that appear in HAL replies.

import { StreamLanguage } from '@codemirror/language'
import { clike } from '@codemirror/legacy-modes/mode/clike'

const halKeywords =
  'loadusr loadrt unloadusr unloadrt ' +
  'addf delf ' +
  'setp sets ' +
  'newsig delsig ' +
  'linkps links unlinkp ' +
  'net ' +
  'show comp'

const halAtoms = 'true false yes no'

export const hal = () =>
  StreamLanguage.define(
    clike({
      name: 'hal',
      keywords: keyWords(halKeywords),
      blockKeywords: '',
      defKeywords: '',
      atoms: keyWords(halAtoms),
      typeFirstDefinitions: false,
      dontAlignCalls: true,
    })
  )

function keyWords(str) {
  const obj = {}
  for (const w of str.split(/\s+/)) {
    if (w) obj[w] = true
  }
  return obj
}
