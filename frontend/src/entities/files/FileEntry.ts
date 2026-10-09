// FileEntry entity — the one shape for every file listing (G-code
// programs, profiles, machine files, M-codes, macros). The backend
// sends the same `FileEntryResponse` from every endpoint; this entity
// is its frontend side (see `mappers/filesMapper.ts`).

export interface FileEntryParams {
  name: string;
  path?: string;
  kind?: string;
  sizeBytes?: number;
  parent?: string | null;
  modified?: string | null;
  readOnly?: boolean;
  hasMarker?: boolean;
}

export class FileEntry {
  private readonly _name: string;
  private readonly _path: string;
  private readonly _kind: "file" | "folder";
  private readonly _sizeBytes: number;
  private readonly _parent: string | null;
  private readonly _modified: string | null;
  private readonly _readOnly: boolean;
  private readonly _hasMarker: boolean;

  constructor({
                name,
                path = "",
                kind = "file",
                sizeBytes = 0,
                parent = null,
                modified = null,
                readOnly = false,
                hasMarker = false,
              }: FileEntryParams) {
    if (typeof name !== "string" || name.length === 0) {
      throw new Error("FileEntry: name must be a non-empty string");
    }

    this._name = name;
    this._path = typeof path === "string" && path.length > 0 ? path : name;
    this._kind = kind === "folder" ? "folder" : "file";
    this._sizeBytes = Number.isFinite(sizeBytes) ? Math.max(0, sizeBytes) : 0;
    this._parent = typeof parent === "string" && parent.length > 0 ? parent : null;
    this._modified = typeof modified === "string" && modified.length > 0 ? modified : null;
    this._readOnly = Boolean(readOnly);
    this._hasMarker = Boolean(hasMarker);
  }

  get name(): string {
    return this._name;
  }

  get path(): string {
    return this._path;
  }

  get kind(): "file" | "folder" {
    return this._kind;
  }

  get sizeBytes(): number {
    return this._sizeBytes;
  }

  get parent(): string | null {
    return this._parent;
  }

  /** ISO-8601 timestamp of the last change, or `null` when unknown. */
  get modified(): string | null {
    return this._modified;
  }

  /** `modified` as epoch milliseconds (0 when unknown) — for sorting. */
  get modifiedMs(): number {
    if (!this._modified) return 0;
    const ms = Date.parse(this._modified);
    return Number.isFinite(ms) ? ms : 0;
  }

  get readOnly(): boolean {
    return this._readOnly;
  }

  /** Profiles only: the file carries the `#Start` marker. */
  get hasMarker(): boolean {
    return this._hasMarker;
  }

  get isFolder(): boolean {
    return this._kind === "folder";
  }

  get isFile(): boolean {
    return this._kind === "file";
  }
}
