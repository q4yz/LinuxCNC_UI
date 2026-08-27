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

const SOURCES = new Set<string>(Object.values(EDITOR_SOURCES))

/**
 * Push a new editor route onto the router.
 */
export function openInEditor({
  source,
  name,
  readOnly = false,
}: {
  source: string;
  name: string;
  readOnly?: boolean;
}) {
  if (!SOURCES.has(source)) {
    throw new Error(
      `openInEditor: invalid source ${JSON.stringify(source)}; ` +
      `expected one of ${[...SOURCES].join(', ')}`,
    )
  }
  if (typeof name !== 'string' || name.length === 0) {
    throw new Error('openInEditor: name must be a non-empty string')
  }
  // The router's typed route resolves ``source`` as the literal
  // ``EditorSource`` union, but at runtime any validated source
  // is acceptable. The runtime check above is the source of
  // truth; this double cast just keeps ts-strict quiet.
  return router.push({
    name: 'editor',
    query: {
      source: source as never,
      name,
      readOnly: readOnly ? 'true' : 'false',
    },
  } as never)
}

export { EDITOR_SOURCES }