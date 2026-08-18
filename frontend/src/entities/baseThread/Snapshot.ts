import { ProgramProgress } from "../progress/ProgramProgress";
import { ReadingSet } from "../temperature/ReadingSet";
import { ToolList } from "../tools/ToolList";

export interface SnapshotParams {
  progress?: ProgramProgress;
  readings?: ReadingSet;
  toolList?: ToolList;
  timestamp?: string | null;
}

export class Snapshot {
  readonly progress: ProgramProgress;
  readonly readings: ReadingSet;
  readonly toolList: ToolList;
  readonly timestamp: string | null;

  constructor(params: SnapshotParams = {}) {
    this.progress = params.progress ?? new ProgramProgress();
    this.readings = params.readings ?? new ReadingSet();
    this.toolList = params.toolList ?? new ToolList([]);
    this.timestamp = params.timestamp ?? null;
  }
}