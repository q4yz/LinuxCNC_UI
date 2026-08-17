// Typed wrapper for entity ids. Newtype-style: keeps the value
// private, exposes it via a getter so the rest of the app cannot
// accidentally compare a string to a different string type.

export class EntityId {
  /**
   * @param {string} value
   * @param {string} [kind] Optional kind tag for debugging
   *  (``"sensor"``, ``"heater"``, ``"tool"``…). Has no semantic
   *  meaning at runtime.
   */
  constructor(value, kind = "entity") {
    if (typeof value !== "string" || value.length === 0) {
      throw new Error(`EntityId(${kind}): value must be a non-empty string`);
    }
    this._value = value;
    this._kind = kind;
  }

  get value() {
    return this._value;
  }

  toString() {
    return this._value;
  }

  equals(other) {
    return other instanceof EntityId && other._value === this._value;
  }
}
