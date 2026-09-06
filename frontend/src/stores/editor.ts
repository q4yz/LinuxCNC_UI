// Universal editor store. Owns every file-I/O concern the editor
// touches so ``EditorView`` (and any other consumer) never has to
// branch on file kind.
//
// Architecture (issue #132 — ``source``-driven dispatch)
// -----------------------------------------------------
//
// The store used to route reads and writes by **filename extension**
// (``modeForFilename(path)`` falling back to a profile path-prefix
// lookup). That was fragile: a ``.cfg.txt`` profile would route to
// the programs endpoint and 404, and a ``.json`` profile would land
// on the same broken branch because the route-by-extension
// fallback only consulted a small whitelist of "profile" modes.
//
// The new model is **source-driven**. Every file the editor opens
// carries an explicit ``source`` from this enum:
//
//     'profiles'   →  GET/PUT /api/v1/modules/machineconfig/profiles/content
//     'active'     →  GET    /api/v1/modules/machineconfig/active/content/{name}
//     'm_codes'    →  GET/PUT /api/v1/modules/machineconfig/m-codes/content
//     'programs'   →  GET/PUT /api/v1/programs/content/{filename}
//     'macros'     →  GET/PUT /api/v1/modules/macros/{name}/content
//     'machine_log' → GET    /api/v1/system/machine/log (read-only)
//
// ``source`` is decided by the caller (typically ``openInEditor``)
// based on **where the file lives**, never by its filename extension.
// The extension is consulted **only** to derive the CodeMirror
// ``syntaxMode`` — a visual overlay, never a routing input.
//
// ``readOnly`` is a boolean (kept for backward-compatible prop
// semantics on ``<Editor :read-only=...>``). ``saveFile`` is a
// no-op when ``readOnly`` is true.

import { defineStore } from 'pinia'

import {
  ProgramFilesService,
  ModulesMachineconfigService,
  ModulesMacrosService,
} from '../../generated/api/index'
import { ApiError } from '../../generated/api/core/ApiError'
import { MachineLifecycleFacade } from '../facades/machineLifecycleFacade'

// ---------------------------------------------------------------------- //
// Source enum                                                              //
// ---------------------------------------------------------------------- //

export const EDITOR_SOURCES = Object.freeze({
  PROFILES: 'profiles',
  MACHINES: 'machines',
  ACTIVE: 'active',
  M_CODES: 'm_codes',
  PROGRAMS: 'programs',
  MACROS: 'macros',
  MACHINE_LOG: 'machine_log',
} as const)
export type EditorSource = (typeof EDITOR_SOURCES)[keyof typeof EDITOR_SOURCES]

// Friendly operator-facing labels. The UI must never leak the raw
// enum (e.g. ``(m_codes)`` looks like an internal tag) so the
// editor header reads the label from this map. New sources need a
// single entry here; ``undefined`` falls back to the raw key so a
// missing label is obvious in dev rather than silent.
export const EDITOR_SOURCE_LABELS: Readonly<Record<EditorSource, string>> = Object.freeze({
  [EDITOR_SOURCES.PROFILES]: 'Profiles',
  [EDITOR_SOURCES.MACHINES]: 'Machine Templates',
  [EDITOR_SOURCES.ACTIVE]:   'Active Config',
  [EDITOR_SOURCES.M_CODES]:  'M-codes',
  [EDITOR_SOURCES.PROGRAMS]: 'G-code Programs',
  [EDITOR_SOURCES.MACROS]:   'Macros',
  [EDITOR_SOURCES.MACHINE_LOG]: 'Console Log',
})

export function sourceLabel(source: string): string {
  return EDITOR_SOURCE_LABELS[source as EditorSource] ?? source
}

const READ_ONLY_SOURCES = new Set<string>([
  EDITOR_SOURCES.ACTIVE,
  EDITOR_SOURCES.MACHINE_LOG,
])

// ---------------------------------------------------------------------- //
// Syntax-highlighting overlay                                              //
// ---------------------------------------------------------------------- //
//
// Comprehensive extension → mode map. The mode is purely a syntax
// highlighting hint; routing is source-driven. New extensions are
// added in one place — keep the list sorted for grep-ability.
// ``modeForFilename`` uses **only the last dot** so a multi-dot name
// like ``printer.cfg.txt`` still picks up its terminal extension's
// mode for CodeMirror's visual overlay without ever leaking back
// into the routing decision.

const EXTENSION_MODES: Record<string, string> = {
  // Machineconfig (Klipper / LinuxCNC INI-style)
  cfg: 'config',
  ini: 'config',
  conf: 'config',
  toml: 'config',
  // LinuxCNC HAL files
  hal: 'hal',
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

// Filename-level overrides that take precedence over the
// extension-based lookup. Used to map a fixed name (whose extension
// would otherwise fall through to ``text``) to a real mode.
const FILENAME_MODES: Record<string, string> = {
  // The platform stores its snapshot as ``config.txt`` even though
  // the payload is JSON. Force JSON highlighting so the operator
  // sees the structure, not a wall of plain text.
  'config.txt': 'json',
}

const DEFAULT_SYNTAX_MODE = 'text'

export function modeForFilename(filename: string): string {
  if (!filename) return DEFAULT_SYNTAX_MODE
  const exact = FILENAME_MODES[filename]
  if (exact) return exact
  const lower = filename.toLowerCase()
  const dot = lower.lastIndexOf('.')
  if (dot < 0) return DEFAULT_SYNTAX_MODE
  const ext = lower.slice(dot + 1)
  return EXTENSION_MODES[ext] ?? DEFAULT_SYNTAX_MODE
}

// ---------------------------------------------------------------------- //
// Source-driven dispatch                                                   //
// ---------------------------------------------------------------------- //
//
// Single point where ``source + name`` → backend call is decided. The
// extension is never consulted here — that's the whole point of the
// refactor. Adding a new source means one new branch + a new entry
// in :data:`EDITOR_SOURCES`.

async function readProfileContent(name: string): Promise<string> {
  const envelope = await ModulesMachineconfigService
    .readProfileApiV1ModulesMachineconfigProfilesContentGet(name)
  return envelope?.content ?? ''
}

async function writeProfileContent(name: string, content: string): Promise<void> {
  await ModulesMachineconfigService
    .saveProfileApiV1ModulesMachineconfigProfilesContentPut(name, { content })
}

async function readMachineContent(name: string): Promise<string> {
  const envelope = await ModulesMachineconfigService
    .readMachineFileApiV1ModulesMachineconfigMachinesContentGet(name)
  return envelope?.content ?? ''
}

async function writeMachineContent(name: string, content: string): Promise<void> {
  await ModulesMachineconfigService
    .saveMachineFileApiV1ModulesMachineconfigMachinesContentPut(name, { content })
}

async function readActiveContent(name: string): Promise<string> {
  const envelope = await ModulesMachineconfigService
    .readActiveApiV1ModulesMachineconfigActiveContentNameGet(name)
  return envelope?.content ?? ''
}

async function readMCodeContent(name: string): Promise<string> {
  const envelope = await ModulesMachineconfigService.readMCode(name)
  return envelope?.content ?? ''
}

async function writeMCodeContent(name: string, content: string): Promise<void> {
  await ModulesMachineconfigService.writeMCode(name, { content })
}

async function readProgramContent(name: string): Promise<string> {
  // ``ProgramFilesService.readFile`` throws ``ApiError`` on 404 —
  // the editor treats that as "brand-new file" and mounts with
  // empty content. Anything else bubbles up.
  try {
    return await ProgramFilesService.readFile(name)
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) return ''
    throw error
  }
}

async function writeProgramContent(name: string, content: string): Promise<void> {
  await ProgramFilesService.writeFile(name, { content })
}

async function readMacroContent(name: string): Promise<string> {
  const { baseName, kind } = _macroSplitName(name)
  const envelope = await ModulesMacrosService.readMacroContent(baseName, kind)
  return envelope?.content ?? ''
}

async function writeMacroContent(name: string, content: string): Promise<void> {
  const { baseName, kind } = _macroSplitName(name)
  await ModulesMacrosService.writeMacroContent(baseName, { content }, kind)
}

// Macros have two on-disk extensions (``.macro`` and ``.ngc``).
// The universal editor treats the **displayed filename** (e.g.
// ``home_all.macro`` / ``home_all.ngc``) as the single ``name``
// payload, so the macros dispatch peels the extension off before
// hitting the backend. The ``.macro`` / ``.ngc`` extension is the
// only signal the dispatch ever consults; bare names default to
// ``macro`` so the legacy ``M<num>`` bare-name flow keeps working
// when ``kind`` cannot be inferred.
function _macroSplitName(name: string): { baseName: string; kind: string } {
  const lower = (name || '').toLowerCase()
  if (lower.endsWith('.ngc')) {
    return { baseName: name.slice(0, -4), kind: 'ngc' }
  }
  if (lower.endsWith('.macro')) {
    return { baseName: name.slice(0, -6), kind: 'macro' }
  }
  return { baseName: name, kind: 'macro' }
}

async function readMachineLogContent(): Promise<string> {
  const result = await MachineLifecycleFacade.getConsoleLog()
  return result.exists
    ? result.log || '(log file is empty — nothing has been written to it yet)'
    : 'No console log yet — start the machine to generate one.'
}

async function dispatchRead(source: EditorSource, name: string): Promise<string> {
  switch (source) {
    case EDITOR_SOURCES.PROFILES: return readProfileContent(name)
    case EDITOR_SOURCES.MACHINES: return readMachineContent(name)
    case EDITOR_SOURCES.ACTIVE:   return readActiveContent(name)
    case EDITOR_SOURCES.M_CODES:  return readMCodeContent(name)
    case EDITOR_SOURCES.PROGRAMS: return readProgramContent(name)
    case EDITOR_SOURCES.MACROS:   return readMacroContent(name)
    case EDITOR_SOURCES.MACHINE_LOG: return readMachineLogContent()
    default:
      throw new Error(`Unknown editor source: ${JSON.stringify(source)}`)
  }
}

async function dispatchWrite(source: EditorSource, name: string, content: string): Promise<void> {
  switch (source) {
    case EDITOR_SOURCES.PROFILES: return writeProfileContent(name, content)
    case EDITOR_SOURCES.MACHINES: return writeMachineContent(name, content)
    case EDITOR_SOURCES.M_CODES:  return writeMCodeContent(name, content)
    case EDITOR_SOURCES.PROGRAMS: return writeProgramContent(name, content)
    case EDITOR_SOURCES.MACROS:   return writeMacroContent(name, content)
    default:
      throw new Error(`Source ${JSON.stringify(source)} is read-only or unknown`)
  }
}

// ---------------------------------------------------------------------- //
// Error formatting                                                         //
// ---------------------------------------------------------------------- //

function describeError(error: unknown): string {
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
  if (error instanceof Error) return error.message
  return String(error)
}

// ---------------------------------------------------------------------- //
// Store                                                                   //
// ---------------------------------------------------------------------- //

interface EditorState {
  source: EditorSource;
  name: string;
  readOnly: boolean;
  syntaxMode: string;
  content: string;
  pristineContent: string;
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
}

export const useEditorStore = defineStore('editor', {
  state: (): EditorState => ({
    // Source-driven identity: the caller pins these via
    // ``open({source, name, ...})``. The URL the operator sees in the
    // browser bar is also derived from these, so the editor is
    // always deep-linkable.
    source: '' as EditorSource,
    name: '',
    // ``readOnly`` is the property the ``<Editor>`` child consumes
    // to gate the editor surface. ``syntaxMode`` is the CodeMirror
    // language pack — purely visual.
    readOnly: false,
    syntaxMode: DEFAULT_SYNTAX_MODE,
    content: '',
    pristineContent: '',
    // Async I/O flags — components watch these to drive spinners.
    isLoading: false,
    isSaving: false,
    // Last error from ``loadFile`` / ``saveFile`` (or ``null``).
    error: null,
  }),

  getters: {
    canSave: (state) => !state.readOnly && state.source.length > 0 && state.name.length > 0,
    hasContent: (state) => state.content.length > 0,
    isDirty: (state) => state.content !== state.pristineContent,
  },

  actions: {
    /**
     * Open the editor on a file identified by ``source`` + ``name``.
     */
    open({
      source,
      name,
      readOnly,
      content = '',
    }: {
      source: string;
      name: string;
      readOnly?: boolean;
      content?: string;
    }) {
      if (!Object.values(EDITOR_SOURCES).includes(source as EditorSource)) {
        throw new Error(`Invalid editor source: ${JSON.stringify(source)}`)
      }
      const sourceValue = source as EditorSource
      this.source = sourceValue
      this.name = name
      // Read-only by default for the two compile-time roots.
      this.readOnly = readOnly ?? READ_ONLY_SOURCES.has(source)
      this.syntaxMode = modeForFilename(name)
      this.content = content
      this.pristineContent = content
      this.error = null
      this.isLoading = false
      this.isSaving = false
    },

    /**
     * Fetch the active ``name`` from ``source``'s backend and write
     * the result into ``state.content``. The caller is expected to
     * have already populated ``source`` / ``name`` (via
     * ``open()``).
     */
    async loadFile() {
      if (!this.source || !this.name) {
        throw new Error('loadFile requires source + name')
      }
      this.isLoading = true
      this.error = null
      try {
        const text = await dispatchRead(this.source, this.name)
        this.content = text
        this.pristineContent = text
      } catch (error: unknown) {
        this.error = describeError(error)
        throw error
      } finally {
        this.isLoading = false
      }
    },

    /**
     * Persist ``content`` to ``source``'s backend. Returns ``true``
     * on success, ``false`` (and sets ``state.error``) on failure.
     */
    async saveFile(content: string) {
      if (this.readOnly) {
        this.error = 'Editor is read-only.'
        return false
      }
      if (!this.source || !this.name) {
        this.error = 'saveFile requires source + name'
        return false
      }
      // FastAPI rejects a zero-byte ``text/plain`` body with
      // ``422``. Normalise ``""`` → ``"\n"`` at the dispatch
      // boundary so every backend write (profile, m-code, macro,
      // program) lands a single newline instead of failing. The
      // envelope-shape endpoints (``m_codes``, ``macros``) accept
      // JSON with an empty string fine; the safety net still costs
      // nothing.
      const safe = content.length === 0 ? '\n' : content

      this.isSaving = true
      this.error = null
      try {
        await dispatchWrite(this.source, this.name, safe)
        this.content = safe
        this.pristineContent = safe
        return true
      } catch (error: unknown) {
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
      this.source = '' as EditorSource
      this.name = ''
      this.readOnly = false
      this.syntaxMode = DEFAULT_SYNTAX_MODE
      this.content = ''
      this.pristineContent = ''
      this.error = null
      this.isLoading = false
      this.isSaving = false
    },
  },
})

// ---- Public re-exports ------------------------------------------- //
//
// External consumers (EditorView, tests, the openInEditor helper)
// import the dispatch helpers + the syntax-mode resolver so the
// public surface stays in one place.

// ``EDITOR_SOURCES`` / ``EDITOR_SOURCE_LABELS`` / ``sourceLabel``
// / ``EXTENSION_MODES`` / ``DEFAULT_SYNTAX_MODE`` are already
// exported via ``export const`` / ``export function`` above.
// ``dispatchRead`` / ``dispatchWrite`` are local — re-export them
// under their public aliases (``readBySource`` / ``writeBySource``)
// so external callers do not reach into the store internals.
export {
  EXTENSION_MODES,
  DEFAULT_SYNTAX_MODE,
  EDITOR_SOURCES as SOURCES,
  dispatchRead as readBySource,
  dispatchWrite as writeBySource,
}
