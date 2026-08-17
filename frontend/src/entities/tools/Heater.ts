import {ExtruderControlRequest} from "./Extruder";

export class HeaterState {
  /** Stable discriminator for v-if dispatch in tool cards. */
  static readonly type = "heater" as const;

  readonly id: string;
  readonly targetCelsius: number;
  readonly actualCelsius: number;
  readonly minTemp: number;
  readonly maxTemp: number;

  constructor(
    data: Partial<Omit<HeaterState, "id" | "isHeating" | "fractionOfTarget">> & {
      id: string;
    }
  ) {
    this.id = data.id;
    this.targetCelsius = data.targetCelsius ?? 0;
    this.actualCelsius = data.actualCelsius ?? 0;
    this.minTemp = data.minTemp ?? 0;
    this.maxTemp = data.maxTemp ?? 300;
  }

  get isHeating(): boolean {
    return this.targetCelsius > 0 && this.actualCelsius < this.targetCelsius;
  }

  get fractionOfTarget(): number {
    if (this.targetCelsius <= 0) return 0;
    return Math.max(0, Math.min(1, this.actualCelsius / this.targetCelsius));
  }
}

export class HeaterControlRequest {
  readonly toolId: string;
  readonly target: number;

  constructor(data: { toolId: string; target: number }) {
    this.toolId = data.toolId;
    this.target = data.target;
  }

  /** Serializes the entity to the backend wire JSON shape. */
  toWire(): Record<string, unknown> {
    return {
      tool_id: this.toolId,
      target: this.target,
    };
  }
}

export const HEATER_TYPE = HeaterState.type;