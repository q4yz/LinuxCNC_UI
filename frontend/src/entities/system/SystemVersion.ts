// System version + updatability entity.

export class SystemVersion {
  private _version: string;
  private _latestVersion: string;
  private _commit: string;
  private _isUpdatable: boolean;
  private _releaseNotes: string | null;

  /**
   * @param {object} params
   * @param {string} [params.version]
   * @param {string} [params.latestVersion]
   * @param {string} [params.commit]
   * @param {boolean} [params.isUpdatable]
   * @param {string|null} [params.releaseNotes]
   */
  constructor({
    version = "",
    latestVersion = "",
    commit = "",
    isUpdatable = false,
    releaseNotes = null as string | null,
  }: {
    version?: string;
    latestVersion?: string;
    commit?: string;
    isUpdatable?: boolean;
    releaseNotes?: string | null;
  } = {}) {
    this._version = typeof version === "string" ? version : "";
    this._latestVersion = typeof latestVersion === "string" ? latestVersion : "";
    this._commit = typeof commit === "string" ? commit : "";
    this._isUpdatable = Boolean(isUpdatable);
    this._releaseNotes = typeof releaseNotes === "string" ? releaseNotes : null;
  }

  get version() {
    return this._version;
  }

  get latestVersion() {
    return this._latestVersion;
  }

  get commit() {
    return this._commit;
  }

  get isUpdatable() {
    return this._isUpdatable;
  }

  get releaseNotes() {
    return this._releaseNotes;
  }
}
