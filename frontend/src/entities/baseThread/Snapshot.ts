import { ProgramProgress } from "../progress/ProgramProgress";
import { ReadingSet } from "../temperature/ReadingSet";
import { ToolList } from "../tools/ToolList";
import { AxisState } from "../axis/AxisState";
import { McuState } from "../mcu/McuState";
import { SpeedOverride } from "../axis/SpeedOverride";
import type { IoState, Led } from "../../../generated/api";

/** No fans / outputs / inputs: before the first snapshot, or none configured. */
export const EMPTY_IO: IoState = Object.freeze({ fans: [], outputs: [], inputs: [] }) as IoState;

export interface SnapshotParams {
  progress?: ProgramProgress;
  readings?: ReadingSet;
  toolList?: ToolList;
  axes?: Record<string, AxisState>;
  mcus?: Record<string, McuState>;
  speedOverride?: SpeedOverride;
  io?: IoState;
  leds?: Led[];
  timestamp?: string | null;
}

export class Snapshot {
  readonly progress: ProgramProgress;
  readonly readings: ReadingSet;
  readonly toolList: ToolList;
  readonly axes: Record<string, AxisState>;
  readonly mcus: Record<string, McuState>;
  readonly speedOverride: SpeedOverride;
  /** Fans, [output_pin]s, [input_pin]s — the I/O card. */
  readonly io: IoState;
  /** [neopixel] chains — the LED card. */
  readonly leds: Led[];
  readonly timestamp: string | null;

  constructor(params: SnapshotParams = {}) {
    this.progress = params.progress ?? new ProgramProgress();
    this.readings = params.readings ?? new ReadingSet();
    this.toolList = params.toolList ?? new ToolList([]);
    this.axes = params.axes ?? {};
    this.mcus = params.mcus ?? {};
    this.speedOverride = params.speedOverride ?? new SpeedOverride();
    this.io = params.io ?? EMPTY_IO;
    this.leds = params.leds ?? [];
    this.timestamp = params.timestamp ?? null;
  }
}