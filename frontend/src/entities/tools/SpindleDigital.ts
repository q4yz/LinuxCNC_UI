

export class SpindleDigital {
  readonly id: string;
  readonly direction: SpindleDirection;
  readonly actualRpm: number;
  readonly isConnected: boolean;
  readonly errorCount: number;
  readonly lastError: string;
  readonly atSpeed: boolean;
  readonly minRpm: number;
  readonly maxRpm: number;

  constructor(data: Partial<SpindleDigital> & { id: string }) {
    this.id = data.id;
    this.direction = data.direction ?? "idle";
    this.actualRpm = data.actualRpm ?? 0;
    this.isConnected = data.isConnected ?? false;
    this.errorCount = data.errorCount ?? 0;
    this.lastError = data.lastError ?? "";
    this.atSpeed = data.atSpeed ?? false;
    this.minRpm = data.minRpm ?? 0;
    this.maxRpm = data.maxRpm ?? 24000;
  }

  get isRunning(): boolean {
    return this.direction !== "idle";
  }

  get fractionOfMax(): number {
    if (this.maxRpm <= 0) return 0;
    return Math.max(0, Math.min(1, this.actualRpm / this.maxRpm));
  }
}

export type SPINDLE_DIRECTIONS  = "forward" | "backward" | "idle";

export class SpindleDigitalControlRequest {
    readonly toolId: string;
    readonly action: SpindleDigitalAction;
    readonly speed: number;
    readonly override: number;
    readonly masterOverride: number;
    readonly masterOverrideEnable: boolean;

    constructor(
        data: Partial<Omit<SpindleDigitalCommand, "toolId" | "action" | "speed">> & {
            toolId: string;
            action: SpindleDigitalAction;
            speed: number;
        }
    ) {
        this.toolId = data.toolId;
        this.action = data.action;
        this.speed = data.speed;
        this.override = data.override ?? 1.0;
        this.masterOverride = data.masterOverride ?? 0;
        this.masterOverrideEnable = data.masterOverrideEnable ?? false;
    }
}