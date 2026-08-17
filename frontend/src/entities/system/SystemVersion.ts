// System version + updatability entity.

export class SystemVersion {
  /**
   * @param {object} params
   * @param {string} [params.version]
   * @param {string} [params.commit]
   * @param {boolean} [params.isUpdatable]
   * @param {string|null} [params.releaseNotes]
   */
  constructor({
    version = "",
    commit = "",
    isUpdatable = false,
    releaseNotes = null,
  } = {}) {
    this._version = typeof version === "string" ? version : "";
    this._commit = typeof commit === "string" ? commit : "";
    this._isUpdatable = Boolean(isUpdatable);
    this._releaseNotes = typeof releaseNotes === "string" ? releaseNotes : null;
  }

  get version() {
    return this._version;
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
