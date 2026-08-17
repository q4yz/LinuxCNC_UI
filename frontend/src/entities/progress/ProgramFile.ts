// Single program-file entry returned by ``GET /api/v1/programs``.
//
// Mirrors the wire shape; constructor tolerates missing fields so
// the dashboard can render even a half-built payload.

export class ProgramFile {
  /**
   * @param {object} params
   * @param {string} params.name
   * @param {string} [params.path]
   * @param {number} [params.sizeBytes]
   * @param {string} [params.kind]
   * @param {string} [params.modified]
   */
  constructor({ name, path = "", sizeBytes = 0, kind = "file", modified = null } = {}) {
    if (typeof name !== "string" || name.length === 0) {
      throw new Error("ProgramFile: name must be a non-empty string");
    }
    this._name = name;
    this._path = typeof path === "string" ? path : name;
    this._sizeBytes = Number.isFinite(sizeBytes) ? Math.max(0, sizeBytes) : 0;
    this._kind = typeof kind === "string" ? kind : "file";
    this._modified = typeof modified === "string" ? modified : null;
  }

  get name() {
    return this._name;
  }

  get path() {
    return this._path;
  }

  get sizeBytes() {
    return this._sizeBytes;
  }

  get kind() {
    return this._kind;
  }

  get modified() {
    return this._modified;
  }
}
