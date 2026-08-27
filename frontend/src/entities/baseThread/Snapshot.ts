import { ProgramProgress } from "../progress/ProgramProgress";
import { ReadingSet } from "../temperature/ReadingSet";
import { ToolList } from "../tools/ToolList";
import { AxisState } from "../axis/AxisState";

export interface SnapshotParams {
  progress?: ProgramProgress;
  readings?: ReadingSet;
  toolList?: ToolList;
  axes?: Record<string, AxisState>;
  timestamp?: string | null;
}

export class Snapshot {
  readonly progress: ProgramProgress;
  readonly readings: ReadingSet;
  readonly toolList: ToolList;
  readonly axes: Record<string, AxisState>;
  readonly timestamp: string | null;

  constructor(params: SnapshotParams = {}) {
    this.progress = params.progress ?? new ProgramProgress();
    this.readings = params.readings ?? new ReadingSet();
    this.toolList = params.toolList ?? new ToolList([]);
    this.axes = params.axes ?? {};
    this.timestamp = params.timestamp ?? null;
  }
}