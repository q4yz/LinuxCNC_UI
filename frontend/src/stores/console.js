import { defineStore } from 'pinia'

// ---------------------------------------------------------------------- //
// Log level vocabulary                                                    //
// ---------------------------------------------------------------------- //
//
// The four canonical levels are surfaced both to the console UI
// (filter chips) and to the backend persistent logger (file row
// prefix). ``All`` is a UI-only sentinel that never appears on a
// message itself.
//
// The mapping from the historic ``type`` vocabulary (info / success /
// command / warning / error) to the new ``level`` vocabulary is:
//
//   * ``info``    -> ``info``     (default)
//   * ``success`` -> ``info``     (positive variant of info)
//   * ``command`` -> ``info``     (user-issued commands are info-
//                                 level events for filtering)
//   * ``warning`` -> ``warning``  (direct carry-over)
//   * ``error``   -> ``error``    (direct carry-over)
//   * ``debug``   -> ``debug``    (new — used by diagnostic logging)

export const LOG_LEVELS = ['all', 'info', 'warning', 'error', 'debug']

const TYPE_TO_LEVEL = {
  info: 'info',
  success: 'info',
  command: 'info',
  warning: 'warning',
  error: 'error',
  debug: 'debug',
}

/**
 * Translate one of the historic ``type`` tokens into the new
 * ``level`` token. Exposed so callers that hand-construct messages
 * can populate the field without having to memorise the table.
 *
 * @param {string} type - The historic type token.
 * @returns {string} The canonical level token.
 */
export const typeToLevel = (type) => TYPE_TO_LEVEL[type] || 'info'

export const useConsoleStore = defineStore('console', {
  state: () => ({
    messages: [],
    // The currently active level filter. ``all`` is the default
    // and means "do not filter". The store is the single source of
    // truth so the chip row in ``ConsolePanel.vue`` and any other
    // component share the same value.
    filterLevel: 'all',
  }),
  getters: {
    /**
     * The messages that should be visible in the console given the
     * current ``filterLevel``. We compute this from the raw
     * ``messages`` array so the renderer never has to read both
     * fields and the cost is paid once per change.
     *
     * ``command`` / ``success`` rows share the ``info`` level, so
     * the ``All`` and ``Info`` filters surface them together.
     */
    filteredMessages: (state) => {
      if (state.filterLevel === 'all') return state.messages
      return state.messages.filter(
        (msg) => (msg.level || typeToLevel(msg.type)) === state.filterLevel,
      )
    },
  },
  actions: {
    addMessage(text, type = 'info') {
      const level = typeToLevel(type)
      this.messages.push({
        id: Date.now() + Math.random().toString(36).substr(2, 9),
        timestamp: new Date().toLocaleTimeString(),
        text,
        type,
        level,
      });
    },
    /**
     * Convenience helper for debug-level rows. Mirrors the historic
     * ``addMessage`` shape so existing callers can drop in without
     * a breaking change.
     */
    addDebug(text) {
      this.addMessage(text, 'debug')
    },
    setFilterLevel(level) {
      if (!LOG_LEVELS.includes(level)) return
      this.filterLevel = level
    },
    clearMessages() {
      this.messages = [];
    },
  },
})
