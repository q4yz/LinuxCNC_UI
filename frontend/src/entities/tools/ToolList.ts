

export type AnySpindle = SpindleState | SpindleAnalogState;
export type ToolItem = AnySpindle | Extruder | HeaterState;

export class ToolList {
  private readonly _byId: Map<string, ToolItem> = new Map();
  private readonly _spindles: AnySpindle[] = [];
  private readonly _extruders: Extruder[] = [];
  private readonly _heaters: HeaterState[] = [];

  constructor(tools: ToolItem[] = []) {
    for (const t of tools) {
      if (t instanceof SpindleState || t instanceof SpindleAnalogState) {
        this._spindles.push(t);
      } else if (t instanceof Extruder) {
        this._extruders.push(t);
      } else if (t instanceof HeaterState) {
        this._heaters.push(t);
      } else {
        continue;
      }
      this._byId.set(t.id, t);
    }
  }

  get size(): number {
    return this._byId.size;
  }

  get(id: string): ToolItem | undefined {
    return this._byId.get(id);
  }

  has(id: string): boolean {
    return this._byId.has(id);
  }

  all(): ToolItem[] {
    return Array.from(this._byId.values());
  }

  spindles(): AnySpindle[] {
    return [...this._spindles];
  }

  extruders(): Extruder[] {
    return [...this._extruders];
  }

  heaters(): HeaterState[] {
    return [...this._heaters];
  }

  ids(): string[] {
    return Array.from(this._byId.keys());
  }

  forEach(
    callback: (value: ToolItem, key: string, map: ToolList) => void,
    thisArg?: unknown
  ): void {
    this._byId.forEach((value, key) => {
      callback.call(thisArg, value, key, this);
    });
  }
}