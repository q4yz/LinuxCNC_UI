import { ProgramProgress } from "../progress/ProgramProgress";
import { ReadingSet } from "../temperature/ReadingSet";
import { ToolList } from "../tools/ToolList";
import { AxisState } from "../axis/AxisState";
import { McuState } from "../mcu/McuState";
import { SpeedOverride } from "../axis/SpeedOverride";

export interface SnapshotParams {
  progress?: ProgramProgress;
  readings?: ReadingSet;
  toolList?: ToolList;
  axes?: Record<string, AxisState>;
  mcus?: Record<string, McuState>;
  speedOverride?: SpeedOverride;
  timestamp?: string | null;
}

export class Snapshot {
  readonly progress: ProgramProgress;
  readonly readings: ReadingSet;
  readonly toolList: ToolList;
  readonly axes: Record<string, AxisState>;
  readonly mcus: Record<string, McuState>;
  readonly speedOverride: SpeedOverride;
  readonly timestamp: string | null;

  constructor(params: SnapshotParams = {}) {
    this.progress = params.progress ?? new ProgramProgress();
    this.readings = params.readings ?? new ReadingSet();
    this.toolList = params.toolList ?? new ToolList([]);
    this.axes = params.axes ?? {};
    this.mcus = params.mcus ?? {};
    this.speedOverride = params.speedOverride ?? new SpeedOverride();
    this.timestamp = params.timestamp ?? null;
  }
}