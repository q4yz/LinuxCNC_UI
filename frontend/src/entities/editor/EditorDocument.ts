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
} as const);
export type EditorSource = (typeof EditorSource)[keyof typeof EditorSource];

export const EDITOR_SOURCES: ReadonlyArray<EditorSource> = Object.freeze(
  Object.values(EditorSource),
);

const READ_ONLY_SOURCES = new Set<string>([EditorSource.ACTIVE, EditorSource.STAGED]);

export const EDITOR_SOURCE_LABELS: Readonly<Record<EditorSource, string>> = Object.freeze({
  [EditorSource.PROFILES]: "Profiles",
  [EditorSource.ACTIVE]: "Active Config",
  [EditorSource.STAGED]: "Compiled Output",
  [EditorSource.M_CODES]: "M-codes",
  [EditorSource.PROGRAMS]: "G-code Programs",
  [EditorSource.MACROS]: "Macros",
});

export function sourceLabel(source: string): string {
  return EDITOR_SOURCE_LABELS[source as EditorSource] ?? source;
}

export function isEditorSource(value: unknown): value is EditorSource {
  return EDITOR_SOURCES.includes(value as EditorSource);
}

export function isReadOnlySource(source: string): boolean {
  return READ_ONLY_SOURCES.has(source);
}

type EditorSourceKey = (typeof EditorSource)[keyof typeof EditorSource];

export class EditorDocument {
  private _source: string;
  private _path: string;
  private _content: string;
  private _readOnly: boolean;

  constructor({
    source,
    path,
    content = "",
    readOnly = false,
  }: {
    source?: string;
    path?: string;
    content?: string;
    readOnly?: boolean;
  } = {}) {
    if (!isEditorSource(source)) {
      throw new Error(`EditorDocument: unknown source ${source}`);
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
