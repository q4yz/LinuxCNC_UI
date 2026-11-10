// The backend's own console messages — homing routine, Z_TILT_ADJUST,
// BED_MESH_CALIBRATE, PROBE_ACCURACY, macros — arrive on the servo-thread
// websocket as ``{"type": "console", "data": {level, text, time}}``.
// No imports, so the node tests load it directly.

export interface ConsoleSink {
    debug(text: string): void;
    info(text: string): void;
    warning(text: string): void;
    error(text: string): void;
}

/** A ``{"type": "console"}`` frame's ``{level, text}`` into the console. */
export function emitBackendConsole(
    consoleStore: ConsoleSink,
    data: unknown,
): void {
    if (!data || typeof data !== "object") return;
    const { level, text } = data as { level?: unknown; text?: unknown };
    if (typeof text !== "string" || !text) return;
    switch (level) {
        case "debug": consoleStore.debug(text); break;
        case "warning": consoleStore.warning(text); break;
        case "error": consoleStore.error(text); break;
        default: consoleStore.info(text);
    }
}
