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

export const LOG_LEVELS = ['all','debug', 'info', 'warning', 'error']

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

      // Get the severity index of the currently active filter
      const filterIndex = LOG_LEVELS.indexOf(state.filterLevel)

      return state.messages.filter((msg) => {
        const level = msg.level || typeToLevel(msg.type)
        const msgIndex = LOG_LEVELS.indexOf(level)

        return msgIndex >= filterIndex
      })
    },
  },
  actions: {
    _addMessage(text, type = 'info') {
      const level = typeToLevel(type)
      this.messages.push({
        id: Date.now() + Math.random().toString(36).substring(2, 11),
        timestamp: new Date().toLocaleTimeString(),
        text: `[${level.toUpperCase()}] ${text}`,
        type,
        level,
      });
    },

    /**
     * @deprecated Use the specific level methods (e.g., info(), error()) instead.
     */
    addMessage(text, type = 'info') {
        console.warn('[ConsoleStore] addMessage() is deprecated. Please use the specific level actions like info(), debug(), or error() instead.')
        this.warning('[ConsoleStore] addMessage() is deprecated. Please use the specific level actions like info(), debug(), or error() instead.')
        this._addMessage(text, type)

    },

    error(text) {
      this._addMessage(text, 'error')
    },

    info(text) {
      this._addMessage(text, 'info')
    },

    debug(text) {
      this._addMessage(text, 'debug')
    },

    warning(text) {
      this._addMessage(text, 'warning')
    },

    command(text) {
      this._addMessage(text, 'command')
    },

    success(text) {
      this._addMessage(text, 'success')
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
