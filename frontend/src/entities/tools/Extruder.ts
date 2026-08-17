import { HeaterState } from "./Heater";

export class Extruder {
  static readonly type = "extruder" as const;

  readonly id: string;
  readonly position: number;
  readonly heater: HeaterState | null;

  constructor(
    data: Partial<Omit<Extruder, "id" | "isControllable">> & {
      id: string;
    }
  ) {
    this.id = data.id;
    this.position = data.position ?? 0;
    this.heater = data.heater ?? null;
  }

  /** Extruders are always controllable (via the heater). */
  get isControllable(): boolean {
    return this.heater !== null;
  }
}


export type ExtruderAction = "extrude" | "retract";
export type HeaterAction = "set" | "noop";

export class ExtruderControlRequest {
  readonly toolId: string;
  readonly action: ExtruderAction;
  readonly distance: number;
  readonly speed: number;
  readonly heater: HeaterCommand | null;
  readonly heaterAction: HeaterAction;

  constructor(
    data: Partial<
      Omit<ExtruderCommand, "toolId" | "action" | "distance" | "speed">
    > & {
      toolId: string;
      action: ExtruderAction;
      distance: number;
      speed: number;
    }
  ) {
    this.toolId = data.toolId;
    this.action = data.action;
    this.distance = data.distance;
    this.speed = data.speed;
    this.heater = data.heater ?? null;
    this.heaterAction = data.heaterAction ?? "noop";
  }
}

export const EXTRUDER_TYPE = Extruder.type;