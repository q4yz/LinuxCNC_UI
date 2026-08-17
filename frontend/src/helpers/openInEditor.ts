// Single point every UI surface uses to open the universal editor
// (issue #132).
//
// Contract
// --------
//     openInEditor({ source, name, readOnly = false })
//
//     source   →  one of EDITOR_SOURCES:
//                   'profiles' | 'active' | 'staged'
//                 | 'm_codes' | 'programs' | 'macros'
//     name     →  filename (or path under ``profiles``)
//     readOnly →  optional; ``active`` / ``staged`` default true
//
// The helper validates ``source`` against the enum so a typo does
// not silently navigate to a route the editor cannot serve.

import router from '../router/index'
import { EDITOR_SOURCES } from '../stores/editor'

const SOURCES = new Set(Object.values(EDITOR_SOURCES))

/**
 * Push a new editor route onto the router.
 *
 * @param {object} options
 * @param {string} options.source
 * @param {string} options.name
 * @param {boolean} [options.readOnly]
 * @returns {Promise<unknown>} The router push's return value.
 */
export function openInEditor({ source, name, readOnly = false }) {
  if (!SOURCES.has(source)) {
    throw new Error(
      `openInEditor: invalid source ${JSON.stringify(source)}; ` +
      `expected one of ${[...SOURCES].join(', ')}`,
    )
  }
  if (typeof name !== 'string' || name.length === 0) {
    throw new Error('openInEditor: name must be a non-empty string')
  }
  return router.push({
    name: 'editor',
    query: {
      source,
      name,
      readOnly: readOnly ? 'true' : 'false',
    },
  })
}

export { EDITOR_SOURCES }