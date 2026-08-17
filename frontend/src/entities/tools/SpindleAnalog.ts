export class SpindleAnalog {
  /** Stable discriminator for v-if dispatch in tool cards. */
  static readonly type = "spindle_analog" as const;
  readonly type = SpindleAnalog.type;
  readonly id: string;
  readonly minV: number;
  readonly maxV: number;
  readonly commandedV: number;
  readonly isEnabled: boolean;

  constructor(
    data: Partial<Omit<SpindleAnalog, "id" | "isRunning">> & {
      id: string;
    }
  ) {
    this.id = data.id;
    this.minV = data.minV ?? 0;
    this.maxV = data.maxV ?? 10;
    this.commandedV = data.commandedV ?? 0;
    this.isEnabled = data.isEnabled ?? false;
  }

  get isRunning(): boolean {
    return this.isEnabled;
  }
}

export const SPINDLE_ANALOG_TYPE = SpindleAnalog.type;