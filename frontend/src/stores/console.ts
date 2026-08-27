import { defineStore } from 'pinia'

// Log level vocabulary. Surfaces to both the console UI (filter
// chips) and the backend persistent logger (file row prefix). ``All``
// is a UI-only sentinel that never appears on a message itself.
// ``info`` absorbs the historic ``info`` / ``success`` / ``command``
// variants; ``warning`` / ``error`` carry over directly; ``debug`` is
// new for diagnostic logging.

export const LOG_LEVELS = ['all','debug', 'info', 'warning', 'error'] as const
export type LogLevel = (typeof LOG_LEVELS)[number]

export type ToastLevel = Exclude<LogLevel, 'all'>

interface ConsoleMessage {
  id: string;
  timestamp: string;
  text: string;
  type: string;
  level: ToastLevel;
}

interface ToastOptions {
  popup?: boolean;
  title?: string;
  lifetime?: number | null;
}

type ToastType = 'info' | 'success' | 'warn' | 'error';

const TYPE_TO_LEVEL: Record<string, ToastLevel> = {
  info: 'info',
  success: 'info',
  command: 'info',
  warning: 'warning',
  error: 'error',
  debug: 'debug',
}

// Maps console level tokens to the toast types the popup layer
// understands. ``warning`` -> ``warn`` because the toast store
// keeps the British spelling. ``debug`` is intentionally absent —
// debug-level popups would be operator noise.
//
// Note: keys are read loosely via ``Record<string, ToastType>``
// because the action entry-points pass through both the legacy
// ``type`` tokens (e.g. ``"success"``) and the canonical
// ``level`` tokens (e.g. ``"info"``); unrecognised keys
// collapse to ``undefined`` so the ``_emitToast`` no-op branch
// fires.
const LEVEL_TO_TOAST_TYPE: Record<string, ToastType> = {
  info: 'info',
  success: 'success',
  warning: 'warn',
  error: 'error',
}

/**
 * Translate one of the historic ``type`` tokens into the new
 * ``level`` token. Exposed so callers that hand-construct messages
 * can populate the field without having to memorise the table.
 *
 * @param {string} type - The historic type token.
 * @returns {string} The canonical level token.
 */
export const typeToLevel = (type: string): ToastLevel => TYPE_TO_LEVEL[type] || 'info'

export const useConsoleStore = defineStore('console', {
  state: (): { messages: ConsoleMessage[]; filterLevel: LogLevel } => ({
    messages: [] as ConsoleMessage[],
    filterLevel: 'info',
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
    filteredMessages: (state): ConsoleMessage[] => {
      if (state.filterLevel === 'all') return state.messages

      // Get the severity index of the currently active filter
      const filterIndex = LOG_LEVELS.indexOf(state.filterLevel)

      return state.messages.filter((msg: ConsoleMessage) => {
        const level = msg.level || typeToLevel(msg.type)
        const msgIndex = LOG_LEVELS.indexOf(level)

        return msgIndex >= filterIndex
      })
    },
  },
  actions: {
    _addMessage(text: string, type: string = 'info') {
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
     * Internal helper that optionally publishes to the toast
     * channel. Resolved inside the action (rather than at module
     * scope) to avoid the cross-store import cycle documented in
     * ``.agent/LESSONS_LEARNED.md`` § 2.4 — circular store
     * imports are a known regression vector. The lazy
     * ``require``-equivalent keeps ``useToastStore`` out of the
     * module-init path so a test harness that mocks Pinia does
     * not crash on import.
     *
     * @param {string} level - One of ``info`` / ``warning`` / ``error`` / ``debug``.
     * @param {string} text  - The console text; also becomes the toast body.
     * @param {ToastOptions} [opts]
     *   ``lifetime`` is in **seconds**. ``undefined`` falls back to
     *   the toast store's default (5 s); ``null`` makes the toast
     *   persist until the operator closes it.
     */
    _emitToast(level: string, text: string, opts?: ToastOptions) {
      if (!opts || !opts.popup) return
      // Dynamic import keeps the dependency one-way and avoids the
      // module-scope Pinia ordering trap.
      import('../core/toast')
        .then(({ useToastStore }) => {
          const toastStore = useToastStore()
          if (!toastStore) return
          const toastType = LEVEL_TO_TOAST_TYPE[level]
          if (!toastType) return
          if (typeof toastStore[toastType] !== 'function') return
          toastStore[toastType](text, {
            title: opts.title,
            lifetime: opts.lifetime,
          })
        })
        .catch(() => {
          // Toast layer is optional; never let a missing store
          // crash the console pipeline.
        })
    },

    error(text: string, opts?: ToastOptions) {
      this._addMessage(text, 'error')
      this._emitToast('error', text, opts)
    },

    info(text: string, opts?: ToastOptions) {
      this._addMessage(text, 'info')
      this._emitToast('info', text, opts)
    },

    debug(text: string, opts?: ToastOptions) {
      this._addMessage(text, 'debug')
      this._emitToast('debug', text, opts)
    },

    warning(text: string, opts?: ToastOptions) {
      this._addMessage(text, 'warning')
      this._emitToast('warning', text, opts)
    },

    command(text: string) {
      this._addMessage(text, 'command')
    },

    success(text: string, opts?: ToastOptions) {
      this._addMessage(text, 'success')
      this._emitToast('success', text, opts)
    },

    setFilterLevel(level: LogLevel) {
      if (!LOG_LEVELS.includes(level)) return
      this.filterLevel = level
    },

    clearMessages() {
      this.messages = [];
    },
  },
})
