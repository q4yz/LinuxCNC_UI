import {ServoThreadStateResponse} from "../../../generated/api";



export type WSEnvelopeType = 'full_state' | 'delta' | 'error' | string;

export class WSEnvelope<T> {
    type: WSEnvelopeType;
    data: T;

    constructor(type: WSEnvelopeType, data: T) {
        this.type = type;
        this.data = data;
    }

    /**
     * Safely deserializes raw JSON text into a typed WSEnvelope instance.
     */
    static fromJSON<T>(jsonString: string): WSEnvelope<T> {
        const parsed = JSON.parse(jsonString);
        if (!parsed || typeof parsed !== 'object' || !('type' in parsed) || !('data' in parsed)) {
            throw new Error('Invalid WebSocket envelope structure');
        }
        return new WSEnvelope<T>(parsed.type, parsed.data);
    }

    /**
     * Specialized parser for ServoThread telemetry frames.
     */
    static fromTelemetryJSON(jsonString: string): WSEnvelope<ServoThreadStateResponse> {
        return WSEnvelope.fromJSON<ServoThreadStateResponse>(jsonString);
    }

    /**
     * Serializes the envelope for outgoing WebSocket transmission.
     */
    toJSON(): string {
        return JSON.stringify({
            type: this.type,
            data: this.data,
        });
    }
}




export class ServoThreadState {
    taskState: number;
    estop: number;
    taskMode: number;
    position: number[];
    actualPosition: number[];
    relativePosition: number[];
    state: number;
    file: string;
    homed: number[];
    interpState: number;
    g5xIndex: number;
    g5xOffset: number[];
    g92Offset: number[];
    currentLine: number;
    totalLines: number;
    errors: unknown[];

    /**
     * Construct from a ``full_state`` / ``delta`` payload. Snake-case
     * field names match the OpenAPI-generated
     * ``ServoThreadStateResponse`` so the same constructor works for
     * both branches of the WS envelope.
     *
     * NOTE: the generated type declares ``errors?: null`` because
     * the backend schema generation quirk — in practice the backend
     * may still ship an array, so we keep the defensive copy.
     */
    constructor(data: ServoThreadStateResponse = {}) {
        this.taskState = data.task_state ?? 1;
        this.estop = data.estop ?? 1;
        this.taskMode = data.task_mode ?? 0;
        this.position = data.position ? [...data.position] : [0, 0, 0, 0, 0, 0, 0, 0, 0];
        this.actualPosition = data.actual_position ? [...data.actual_position] : [0, 0, 0, 0, 0, 0, 0, 0, 0];
        this.relativePosition = data.relative_position ? [...data.relative_position] : [0, 0, 0, 0, 0, 0, 0, 0, 0];
        this.state = data.state ?? 0;
        this.file = data.file ?? '';
        this.homed = data.homed ? [...data.homed] : [0, 0, 0];
        this.interpState = data.interp_state ?? 1;
        this.g5xIndex = data.g5x_index ?? 1;
        this.g5xOffset = data.g5x_offset ? [...data.g5x_offset] : [0, 0, 0, 0, 0, 0, 0, 0, 0];
        this.g92Offset = data.g92_offset ? [...data.g92_offset] : [0, 0, 0, 0, 0, 0, 0, 0, 0];
        this.currentLine = data.current_line ?? 0;
        this.totalLines = data.total_lines ?? 0;
        this.errors = data.errors ? [...data.errors] : [];
    }

    /**
     * Applies an incoming delta patch to the existing state. Only
     * touches fields that are present + non-null in ``delta`` so a
     * single-field diff never blanks the rest of the payload.
     *
     * IMPORTANT: call this through the reactive proxy wrapping the
     * entity (i.e. ``status.value.patch(...)``) so the property
     * writes go through Vue's ``set`` trap. Calling
     * ``instance.patch(...)`` directly on a non-reactive handle
     * silently drops the update because the ``Ref`` does not see
     * the change.
     */
    patch(delta: ServoThreadStateResponse): void {
        if (delta.task_state !== undefined && delta.task_state !== null) this.taskState = delta.task_state;
        if (delta.estop !== undefined && delta.estop !== null) this.estop = delta.estop;
        if (delta.task_mode !== undefined && delta.task_mode !== null) this.taskMode = delta.task_mode;
        if (delta.position !== undefined && delta.position !== null) this.position = [...delta.position];
        if (delta.actual_position !== undefined && delta.actual_position !== null) this.actualPosition = [...delta.actual_position];
        if (delta.relative_position !== undefined && delta.relative_position !== null) this.relativePosition = [...delta.relative_position];
        if (delta.state !== undefined && delta.state !== null) this.state = delta.state;
        if (delta.file !== undefined && delta.file !== null) this.file = delta.file;
        if (delta.homed !== undefined && delta.homed !== null) this.homed = [...delta.homed];
        if (delta.interp_state !== undefined && delta.interp_state !== null) this.interpState = delta.interp_state;
        if (delta.g5x_index !== undefined && delta.g5x_index !== null) this.g5xIndex = delta.g5x_index;
        if (delta.g5x_offset !== undefined && delta.g5x_offset !== null) this.g5xOffset = [...delta.g5x_offset];
        if (delta.g92_offset !== undefined && delta.g92_offset !== null) this.g92Offset = [...delta.g92_offset];
        if (delta.current_line !== undefined && delta.current_line !== null) this.currentLine = delta.current_line;
        if (delta.total_lines !== undefined && delta.total_lines !== null) this.totalLines = delta.total_lines;
        if (delta.errors !== undefined && delta.errors !== null) this.errors = [...(delta.errors as unknown as unknown[])];
    }

    // --- Convenience Getters ---

    get isEstop(): boolean {
        return this.estop === 1;
    }

    get isMachineOn(): boolean {
        return this.taskState === 4;
    }

    get isPrinting(): boolean {
        return this.taskState === 2 && this.interpState !== 3;
    }

    get isPaused(): boolean {
        return this.taskState === 2 && this.interpState === 3;
    }

    get printProgress(): number {
        if (this.totalLines <= 0 || this.currentLine < 0) return 0;
        return Math.min(100, (this.currentLine / this.totalLines) * 100);
    }

}