// Single program-file entry returned by `GET /api/v1/programs`.
//
// Mirrors the wire shape; constructor tolerates missing fields so
// the dashboard can render even a half-built payload.

export interface ProgramFileParams {
  name: string;
  path?: string;
  sizeBytes?: number;
  kind?: string;
  modified?: string | null;
}

export class ProgramFile {
  private readonly _name: string;
  private readonly _path: string;
  private readonly _sizeBytes: number;
  private readonly _kind: string;
  private readonly _modified: string | null;

  constructor({
                name,
                path = "",
                sizeBytes = 0,
                kind = "file",
                modified = null,
              }: ProgramFileParams) {
    if (typeof name !== "string" || name.length === 0) {
      throw new Error("ProgramFile: name must be a non-empty string");
    }

    this._name = name;
    // Runtime safeguard in case a non-string payload bypasses the TS types
    this._path = typeof path === "string" ? path : name;
    this._sizeBytes = Number.isFinite(sizeBytes) ? Math.max(0, sizeBytes) : 0;
    this._kind = typeof kind === "string" ? kind : "file";
    this._modified = typeof modified === "string" ? modified : null;
  }

  get name(): string {
    return this._name;
  }

  get path(): string {
    return this._path;
  }

  get sizeBytes(): number {
    return this._sizeBytes;
  }

  get kind(): string {
    return this._kind;
  }

  get modified(): string | null {
    return this._modified;
  }
}