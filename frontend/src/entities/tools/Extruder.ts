import type { HeaterCommand, ExtruderCommand } from "../../../generated/api";
import { HeaterState } from "./Heater";

export class Extruder {
  static readonly type = "extruder" as const;
  readonly type = Extruder.type;
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
  static readonly type = "extruder" as const;
  readonly toolId: string;
  readonly action: ExtruderAction;
  readonly distance: number;
  readonly speed: number;
  readonly heater: HeaterCommand | null;
  readonly heaterAction: HeaterAction;

constructor(
    data: Partial<
      Omit<ExtruderCommand, "toolId" | "action" | "speed" | "distance">
    > & {
      toolId: string;
      action: ExtruderAction;
      distance: number;
      speed: number;
      // Accept both the wire snake_case name and the entity camelCase
      // name so consumers can use whichever fits their context.
      heater_action?: HeaterAction;
      heaterAction?: HeaterAction;
    }
  ) {
    this.toolId = data.toolId;
    this.action = data.action;
    this.distance = data.distance;
    this.speed = data.speed;
    this.heater = data.heater ?? null;
    // The wire-derived base type carries ``heater_action`` (snake_case);
    // legacy call sites pass camelCase ``heaterAction``. Accept both.
    this.heaterAction = (data.heater_action ?? data.heaterAction) as HeaterAction | undefined ?? "noop";
  }
}

export const EXTRUDER_TYPE = Extruder.type;