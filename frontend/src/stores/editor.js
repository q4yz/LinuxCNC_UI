import { defineStore } from 'pinia'

import {
  ProgramFilesService,
  ModulesMachineconfigService,
} from '../../generated/api/index.ts'
import { ApiError } from '../../generated/api/core/ApiError'

// Universal editor store. Owns every file-I/O concern the editor
// touches so ``EditorView`` (and any other consumer) never has to
// branch on file kind.
//
// Modes:
//
// * ``"config"`` / ``"profile"`` / ``"ini"`` / ``"cfg"``  — Klipper /
//   LinuxCNC configuration files under ``machine_config/profiles/``.
//   Served by ``ModulesMachineconfigService``'s
//   ``readProfileApiV1ModulesMachineconfigProfilesContentGet`` /
//   ``saveProfileApiV1ModulesMachineconfigProfilesContentPut``
//   (``?path=<rel>`` query parameter — not a path segment).
//
// * ``"gcode"``  — G-code files under ``nc_files/``. Served by
//   ``ProgramFilesService``'s ``readFile`` / ``writeFile``
//   (``/api/v1/programs/content/{filename}``).
//
// * ``"js"`` / ``"javascript"`` / ``"json"`` / ``"text"`` — read-only
//   convenience modes. ``loadFile`` works (via the config endpoint
//   by default), ``saveFile`` rejects with an error.

const PROFILE_MODES = new Set(['config', 'profile', 'ini', 'cfg'])
const GCODE_MODES = new Set(['gcode', 'ngc', 'nc'])

// ---- Service wrappers ------------------------------------------- //
//
// Two thin wrappers around the generated clients that give us a
// stable interface inside this store. They exist for two reasons:
//
// 1. The codegen emits long path-derived function names like
//    ``readProfileApiV1ModulesMachineconfigProfilesContentGet``
//    that are brittle (renaming the route regenerates the name).
//    A wrapper here means the store has exactly one call site to
//    update when the generator churns. Setting ``operation_id``
//    on the FastAPI decorator would shorten these to ``readProfile``
//    / ``saveProfile`` and make the wrappers stable across regens.
//
// 2. The config endpoint wraps its body in a JSON envelope
//    (``ProfileContent`` model) while the G-code endpoint returns
//    raw text. The wrappers normalise both shapes to a plain
//    string so callers don't have to branch on mode.

async function readConfigContent(path) {
  const envelope = await ModulesMachineconfigService
    .readProfileApiV1ModulesMachineconfigProfilesContentGet(path)
  return envelope?.content ?? ''
}

async function writeConfigContent(path, content) {
    console.log(path)
    console.log(content)
  await ModulesMachineconfigService
    .saveProfileApiV1ModulesMachineconfigProfilesContentPut(path, {
      content
    })
}

async function readGcodeContent(filename) {
  // ``ProgramFilesService.readFile`` throws ``ApiError`` on 404 —
  // the editor treats that as "brand-new file" and mounts with
  // empty content. Anything else bubbles up.
  try {
    return await ProgramFilesService.readFile(filename)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return ''
    throw error
  }
}

async function writeGcodeContent(filename, content) {
  await ProgramFilesService.writeFile(filename, { content })
}

// Human-readable error for both ``ApiError`` (from the generated
// clients) and plain ``Error`` (from anywhere else).
function describeError(error) {
  if (!error) return 'Unknown error'
  if (error instanceof ApiError) {
    return (
      error.body?.detail ||
      error.body?.message ||
      error.statusText ||
      error.message ||
      `HTTP ${error.status}`
    )
  }
  return error.message || String(error)
}

export const useEditorStore = defineStore('editor', {
  state: () => ({
    filename: '',
    mode: 'config',
    content: '',
    pristineContent: '',
    readOnly: false,
    // Async I/O flags — components watch these to drive spinners.
    isLoading: false,
    isSaving: false,
    // Last error from ``loadFile`` / ``saveFile`` (or ``null``).
    error: null
  }),

  getters: {
    isGcode: (state) => GCODE_MODES.has(state.mode),
    isProfile: (state) => PROFILE_MODES.has(state.mode),
    canSave: (state) => !state.readOnly && state.filename.length > 0,
    // True when ``loadFile`` was bypassed because the content was
    // already populated by the caller (e.g. ``FileManager`` passing
    // it in up-front).
    hasContent: (state) => state.content.length > 0,
    isDirty: (state) => state.content !== state.pristineContent
  },

  actions: {
    /**
     * Open the editor on a file. ``content`` is optional; pass
     * ``''`` to let ``loadFile`` fetch from the backend on demand.
     */
    open(filename, readOnly = false, mode = 'config', content = '') {
      this.filename = filename
      this.readOnly = readOnly
      this.mode = mode
      this.content = content
      this.pristineContent = content
      this.error = null
      this.isLoading = false
      this.isSaving = false
    },

    /**
     * Fetch ``path`` from the appropriate backend endpoint for
     * ``mode`` and write the result into ``state.content``. The
     * caller is expected to have already populated ``filename`` /
     * ``mode`` (typically via ``open()``).
     *
     * Mode → service mapping is the single source of truth for
     * which endpoint to hit. No raw URLs, no ``/config/``
     * fallbacks — every branch dispatches through one of the
     * generated clients above.
     */
    async loadFile(path, mode) {
      this.isLoading = true
      this.error = null
      try {
        const effectiveMode = mode ?? this.mode
        const text = await dispatchRead(effectiveMode, path)
        this.content = text
        this.pristineContent = text
        this.filename = path
        this.mode = effectiveMode
      } catch (error) {
        this.error = describeError(error)
        throw error
      } finally {
        this.isLoading = false
      }
    },

    /**
     * Persist ``content`` to ``path`` via the appropriate backend
     * endpoint for ``mode``. Returns ``true`` on success, ``false``
     * (and sets ``state.error``) on failure.
     */
    async saveFile(path, content, mode) {
      if (this.readOnly) {
        this.error = 'Editor is read-only.'
        return false
      }
      const effectiveMode = mode ?? this.mode
      if (!PROFILE_MODES.has(effectiveMode) && !GCODE_MODES.has(effectiveMode)) {
        this.error = `Saving is not supported in mode "${effectiveMode}".`
        return false
      }

      this.isSaving = true
      this.error = null
      try {
        await dispatchWrite(effectiveMode, path, content)
        this.content = content
        this.pristineContent = content
        this.filename = path
        this.mode = effectiveMode
        return true
      } catch (error) {
        this.error = describeError(error)
        return false
      } finally {
        this.isSaving = false
      }
    },

    /**
     * Clear the editor state. The next ``open()`` starts fresh.
     */
    close() {
      this.filename = ''
      this.content = ''
      this.pristineContent = ''
      this.error = null
      this.isLoading = false
      this.isSaving = false
    }
  }
})

// ---- Service dispatch ------------------------------------------- //
//
// Single point where mode → service call is decided. Adding a
// new file kind means one new branch here, nothing else changes.

async function dispatchRead(mode, path) {
  if (GCODE_MODES.has(mode)) {
    return readGcodeContent(path)
  }
  if (PROFILE_MODES.has(mode)) {
    return readConfigContent(path)
  }
  throw new Error(`No read handler configured for mode "${mode}"`)
}

async function dispatchWrite(mode, path, content) {
  if (GCODE_MODES.has(mode)) {
    return writeGcodeContent(path, content)
  }
  if (PROFILE_MODES.has(mode)) {
    return writeConfigContent(path, content)
  }
  throw new Error(`No write handler configured for mode "${mode}"`)
}

export const EDITOR_MODES = {
  CONFIG: 'config',
  PROFILE: 'profile',
  GCODE: 'gcode',
  JS: 'js',
  JSON: 'json',
  TEXT: 'text'
}