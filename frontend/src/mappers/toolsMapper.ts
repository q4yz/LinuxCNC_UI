import type {
  ExtruderCommand,
  ExtruderStateResponse,
  HeaterCommand,
  HeaterStateResponse,
  SpindleDigitalCommand,
  SpindleDigitalStateResponse,
} from "../../generated/api";
import {
  SpindleDigital as SpindleState,
  SpindleDigitalControlRequest,
  type SpindleDirection
} from "../entities/tools/SpindleDigital";
import {HeaterControlRequest, HeaterState} from "../entities/tools/Heater";
import {Extruder, ExtruderControlRequest} from "../entities/tools/Extruder";
import {SpindleAnalog as SpindleAnalogState} from "../entities/tools/SpindleAnalog";
import {ToolItem, ToolList} from "../entities/tools/ToolList";

// Analog fallback if your backend ever adds an analog type
export interface AnalogSpindleWire {
  type: "spindle_analog";
  id: string;
  min_v?: number;
  max_v?: number;
  commanded_v?: number;
  is_enabled?: boolean;
}

export type AnyToolWire =
  | SpindleDigitalStateResponse
  | HeaterStateResponse
  | ExtruderStateResponse
  | AnalogSpindleWire;

// --- Mappers ---

/**
 * Dispatch a single wire row to the right entity using the strict `type` discriminator.
 */
export function toToolState(wire: AnyToolWire | Record<string, any> | null | undefined): ToolItem | null {
  if (!wire || typeof wire !== "object" || !("type" in wire)) return null;

  switch (wire.type) {
    case "extruder":
      return toExtruderState(wire as ExtruderStateResponse);

    case "heater":
      return toHeaterState(wire as HeaterStateResponse);

    case "spindle_digital":
      return toSpindleState(wire as SpindleDigitalStateResponse);

    case "spindle_analog":
      return toSpindleAnalogState(wire as AnalogSpindleWire);

    default:
      console.warn(`[toolsMapper] Unknown tool type received: ${wire.type}`);
      return null;
  }
}

export function toToolList(arr: AnyToolWire[] | null | undefined): ToolList {
  if (!Array.isArray(arr)) return new ToolList([]);

  const tools: ToolItem[] = [];
  for (const wire of arr) {
    const t = toToolState(wire);
    if (t) tools.push(t);
  }
  return new ToolList(tools);
}

export function toSpindleState(wire: SpindleDigitalStateResponse): SpindleState {
  return new SpindleState({
    id: wire.id,
    direction: (typeof wire.state === "string" ? wire.state : "idle") as SpindleDirection,
    actualRpm: Number(wire.actual_rpm) || 0,
    isConnected: Boolean(wire.is_connected),
    errorCount: Number(wire.error_count) || 0,
    lastError: typeof wire.last_error === "string" ? wire.last_error : "",
    atSpeed: Boolean(wire.spindle_at_speed),
    minRpm: Number(wire.min_rpm) || 0,
    maxRpm: Number(wire.max_rpm) || 24000,
  });
}

export function toSpindleAnalogState(wire: AnalogSpindleWire): SpindleAnalogState {
  return new SpindleAnalogState({
    id: wire.id,
    minV: Number(wire.min_v) || 0,
    maxV: Number(wire.max_v) || 10,
    commandedV: Number(wire.commanded_v) || 0,
    isEnabled: Boolean(wire.is_enabled),
  });
}

export function toExtruderState(wire: ExtruderStateResponse): Extruder {
  return new Extruder({
    id: wire.id,
    position: Number(wire.position) || 0,
    heater: wire.heater ? toHeaterState(wire.heater) : null,
  });
}

export function toHeaterState(wire: HeaterStateResponse): HeaterState {
  return new HeaterState({
    id: wire.tool_id || "unknown_heater",
    actualCelsius: Number(wire.actual) || 0,
    targetCelsius: Number(wire.target) || 0,
    minTemp: Number.isFinite(Number(wire.min_temp)) ? Number(wire.min_temp) : 0,
    maxTemp: Number.isFinite(Number(wire.max_temp)) ? Number(wire.max_temp) : 300,
  });
}

// --- Command Factories ---

export function toSpindleCommand(params: SpindleDigitalControlRequest): SpindleDigitalCommand {
  return {
    tool_id: params.toolId,
    action: params.action,
    speed: params.speed,
    master_override: params.masterOverride ?? 0,
    master_override_enable: params.masterOverrideEnable ?? false,
    override: params.override ?? 1.0,
  };
}

export function toExtruderCommand(params: ExtruderControlRequest): ExtruderCommand {
  return {
    tool_id: params.toolId,
    action: params.action,
    distance: params.distance,
    speed: params.speed,
    heater_action: params.heaterAction ?? "noop",
  };
}

export function toHeaterCommand(params: HeaterControlRequest): HeaterCommand {
  return { tool_id: params.toolId, target: params.target };
}