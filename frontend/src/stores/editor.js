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
// Architecture
// ------------
//
// The store used to route reads and writes by ``mode`` (which was
// derived from the file extension). That was fragile: a ``.cfg``
// file under ``nc_files/`` would go through the machineconfig
// endpoint, a ``.gcode`` under ``machine_config/profiles/`` would
// go through the programs endpoint — neither of which matches where
// the file actually lives.
//
// The new model is **path-based**. ``routeByPath(path)`` inspects
// the path prefix and picks the right backend. The ``mode`` field is
// kept for **syntax highlighting** and **UI hints** — it no longer
// affects I/O routing.
//
// Path → service
// --------------
//
//   ``machine_config/...``  or  ``profiles/...``  →  machineconfig
//   everything else                                  →  programs
//
// The ``profiles/`` prefix is an alias accepted by the machineconfig
// router (``save_profile`` and ``read_profile`` resolve relative to
// ``machine_config/profiles/``). Operators see ``profiles/foo.cfg`` in
// the URL bar; the service transparently maps that to the on-disk
// path.
//
// Future-proofing
// ---------------
//
// G-code macros, M-codes, MDI snippets, etc. all live under
// ``nc_files/`` in the programs root. The path-based router extends
// to a new endpoint without changing the existing one — when a
// "macro library" feature lands, the macros are served by the
// programs service and the existing logic handles them.

const PROFILE_PATH_PREFIXES = ['machine_config/', 'profiles/']
const PROFILE_MODES = new Set(['config', 'profile', 'ini', 'cfg', 'conf'])
const GCODE_MODES = new Set(['gcode', 'ngc', 'nc'])

function isProfilePath(path) {
  if (!path) return false
  return PROFILE_PATH_PREFIXES.some(
    (prefix) => path === prefix.slice(0, -1) || path.startsWith(prefix),
  )
}

// Comprehensive extension → mode map. The mode is purely a syntax
// highlighting hint; routing is path-based. New extensions are
// added in one place — keep the list sorted for grep-ability.
const EXTENSION_MODES = {
  // Machineconfig (Klipper / LinuxCNC INI-style)
  cfg: 'config',
  ini: 'config',
  conf: 'config',
  toml: 'config',
  // Programs (G-code)
  gcode: 'gcode',
  ngc: 'gcode',
  nc: 'gcode',
  // Code
  py: 'python',
  js: 'javascript',
  mjs: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  jsx: 'javascript',
  json: 'json',
  // Web
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'css',
  sass: 'css',
  xml: 'xml',
  svg: 'xml',
  // Docs / data
  md: 'markdown',
  yml: 'yaml',
  yaml: 'yaml',
  toml_data: 'yaml',
  // Shell / config
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
}

const DEFAULT_MODE = 'text'

export function modeForFilename(filename) {
  if (!filename) return DEFAULT_MODE
  const lower = filename.toLowerCase()
  const dot = lower.lastIndexOf('.')
  if (dot < 0) return DEFAULT_MODE
  const ext = lower.slice(dot + 1)
  return EXTENSION_MODES[ext] ?? DEFAULT_MODE
}

// ---- Service dispatch ------------------------------------------- //
//
// Single point where path → service call is decided. Adding a
// new file kind means one new branch here, nothing else changes.

async function readProfileContent(path) {
  const envelope = await ModulesMachineconfigService
    .readProfileApiV1ModulesMachineconfigProfilesContentGet(path)
  return envelope?.content ?? ''
}

async function writeProfileContent(path, content) {
  await ModulesMachineconfigService
    .saveProfileApiV1ModulesMachineconfigProfilesContentPut(path, {
      content,
    })
}

async function readProgramContent(filename) {
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

async function writeProgramContent(filename, content) {
  await ProgramFilesService.writeFile(filename, { content })
}

function routeByPath(path) {
  if (isProfilePath(path)) return 'profile'
  return 'program'
}

async function readByPath(path) {
  return routeByPath(path) === 'profile'
    ? readProfileContent(path)
    : readProgramContent(path)
}

async function writeByPath(path, content) {
  return routeByPath(path) === 'profile'
    ? writeProfileContent(path, content)
    : writeProgramContent(path, content)
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
     * ``mode`` defaults to the value derived from the filename
     * extension (see :func:`modeForFilename`) so the editor picks
     * the right syntax highlighting automatically.
     */
    open(filename, readOnly = false, mode = null, content = '') {
      this.filename = filename
      this.readOnly = readOnly
      this.mode = mode ?? modeForFilename(filename)
      this.content = content
      this.pristineContent = content
      this.error = null
      this.isLoading = false
      this.isSaving = false
    },

    /**
     * Fetch ``path`` from the backend (route chosen by path prefix,
     * not by mode) and write the result into ``state.content``.
     * The caller is expected to have already populated ``filename`` /
     * ``mode`` (typically via ``open()``).
     */
    async loadFile(path, mode) {
      this.isLoading = true
      this.error = null
      try {
        const effectiveMode = mode ?? this.mode ?? modeForFilename(path)
        const text = await readByPath(path)
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
     * Persist ``content`` to ``path`` via the backend service picked
     * by path prefix. Returns ``true`` on success, ``false`` (and
     * sets ``state.error``) on failure.
     */
    async saveFile(path, content, mode) {
      if (this.readOnly) {
        this.error = 'Editor is read-only.'
        return false
      }
      const effectiveMode = mode ?? this.mode ?? modeForFilename(path)

      this.isSaving = true
      this.error = null
      try {
        await writeByPath(path, content)
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

// ---- Public re-exports ------------------------------------------- //
//
// External consumers (EditorView's modeForFilename, tests) need
// access to the mode map. Re-export from the store so the public
// surface stays in one place.

export {
  EXTENSION_MODES,
  DEFAULT_MODE,
  isProfilePath,
  modeForFilename as resolveEditorMode,
}

export const EDITOR_MODES = {
  CONFIG: 'config',
  PROFILE: 'profile',
  GCODE: 'gcode',
  JS: 'javascript',
  JSON: 'json',
  PYTHON: 'python',
  MARKDOWN: 'markdown',
  YAML: 'yaml',
  SHELL: 'shell',
  TEXT: 'text'
}
