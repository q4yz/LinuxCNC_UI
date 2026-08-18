// FileEntry entity. Single node in a directory listing (file or
// folder). Mirrors the wire shape produced by the file-listing
// endpoints (`/api/v1/programs`, `/api/v1/modules/machineconfig/profiles/tree`,
// etc.).


import {FileInfo} from "../../../generated/api";

/**
 * Represents the various possible wire shapes from different backend endpoints,
 * including the strictly typed `FileInfo` DTO.
 */
export type WireFile = Partial<FileInfo> & {
  name?: string;
  path?: string;
  kind?: string;
  sizeBytes?: number;
  parent?: string;
  read_only?: boolean;
  readOnly?: boolean;
};

export interface FileEntryParams {
  name: string;
  path?: string;
  kind?: string;
  sizeBytes?: number;
  parent?: string | null;
  modified?: string | null;
  readOnly?: boolean;
}

export class FileEntry {
  private readonly _name: string;
  private readonly _path: string;
  private readonly _kind: "file" | "folder";
  private readonly _sizeBytes: number;
  private readonly _parent: string | null;
  private readonly _modified: string | null;
  private readonly _readOnly: boolean;

  constructor({
                name,
                path = "",
                kind = "file",
                sizeBytes = 0,
                parent = null,
                modified = null,
                readOnly = false,
              }: FileEntryParams) {
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

  get modified(): string | null {
    return this._modified;
  }

  get readOnly(): boolean {
    return this._readOnly;
  }

  get isFolder(): boolean {
    return this._kind === "folder";
  }

  get isFile(): boolean {
    return this._kind === "file";
  }
}