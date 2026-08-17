// FileEntry entity. Single node in a directory listing (file or
// folder). Mirrors the wire shape produced by the file-listing
// endpoints (``/api/v1/programs``, ``/api/v1/modules/machineconfig/profiles/tree``,
// etc.).

export class FileEntry {
  /**
   * @param {object} params
   * @param {string} params.name
   * @param {string} [params.path]
   * @param {string} [params.kind]
   * @param {number} [params.sizeBytes]
   * @param {string|null} [params.parent]
   * @param {string|null} [params.modified]
   * @param {boolean} [params.readOnly]
   */
  constructor({
    name,
    path = "",
    kind = "file",
    sizeBytes = 0,
    parent = null,
    modified = null,
    readOnly = false,
  } = {}) {
    if (typeof name !== "string" || name.length === 0) {
      throw new Error("FileEntry: name must be a non-empty string");
    }
    this._name = name;
    this._path = typeof path === "string" && path.length > 0 ? path : name;
    this._kind = kind === "folder" ? "folder" : "file";
    this._sizeBytes = Number.isFinite(sizeBytes) ? Math.max(0, sizeBytes) : 0;
    this._parent = typeof parent === "string" ? parent : null;
    this._modified = typeof modified === "string" ? modified : null;
    this._readOnly = Boolean(readOnly);
  }

  get name() {
    return this._name;
  }

  get path() {
    return this._path;
  }

  get kind() {
    return this._kind;
  }

  get sizeBytes() {
    return this._sizeBytes;
  }

  get parent() {
    return this._parent;
  }

  get modified() {
    return this._modified;
  }

  get readOnly() {
    return this._readOnly;
  }

  get isFolder() {
    return this._kind === "folder";
  }

  get isFile() {
    return this._kind === "file";
  }
}
