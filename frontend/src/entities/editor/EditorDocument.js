// EditorSource enum + EditorDocument entity.
//
// ``EditorSource`` is the canonical key the editor store uses to
// pick an endpoint (replaces the legacy ``source`` string on file
// records). ``EditorDocument`` carries the read result + the
// read-only bit the editor view consumes.

export const EditorSource = Object.freeze({
  PROFILES: "profiles",
  ACTIVE: "active",
  STAGED: "staged",
  M_CODES: "m_codes",
  PROGRAMS: "programs",
  MACROS: "macros",
});

export const EDITOR_SOURCES = Object.freeze(Object.values(EditorSource));

const READ_ONLY_SOURCES = new Set([EditorSource.ACTIVE, EditorSource.STAGED]);

export const EDITOR_SOURCE_LABELS = Object.freeze({
  [EditorSource.PROFILES]: "Profiles",
  [EditorSource.ACTIVE]: "Active Config",
  [EditorSource.STAGED]: "Compiled Output",
  [EditorSource.M_CODES]: "M-codes",
  [EditorSource.PROGRAMS]: "G-code Programs",
  [EditorSource.MACROS]: "Macros",
});

export function sourceLabel(source) {
  return EDITOR_SOURCE_LABELS[source] ?? source;
}

export function isEditorSource(value) {
  return EDITOR_SOURCES.includes(value);
}

export function isReadOnlySource(source) {
  return READ_ONLY_SOURCES.has(source);
}

export class EditorDocument {
  /**
   * @param {object} params
   * @param {string} params.source EditorSource value
   * @param {string} params.path
   * @param {string} [params.content]
   * @param {boolean} [params.readOnly]
   */
  constructor({ source, path, content = "", readOnly = false } = {}) {
    if (!isEditorSource(source)) {
      throw new Error(`EditorDocument: unknown source ${source!r}`);
    }
    if (typeof path !== "string" || path.length === 0) {
      throw new Error("EditorDocument: path must be a non-empty string");
    }
    this._source = source;
    this._path = path;
    this._content = typeof content === "string" ? content : "";
    this._readOnly = Boolean(readOnly) || isReadOnlySource(source);
  }

  get source() {
    return this._source;
  }

  get path() {
    return this._path;
  }

  get content() {
    return this._content;
  }

  get readOnly() {
    return this._readOnly;
  }

  get label() {
    return sourceLabel(this._source);
  }
}
