// LinuxCNC error kind → human-readable translation.
//
// Background
// ----------
// `error_channel.poll()` returns ``(kind, text)`` tuples where
// ``kind`` is a small integer the LinuxCNC NML stack stamps on
// every error. The integer is stable across the upstream sources
// (see ``src/emc/nml_intf/emc.hh``) and is the same number the AXIS
// GUI would surface as a tooltip. We keep the integer on every
// error so a power-user can grep the LinuxCNC source for the
// exact code, but operators usually want to read a one-liner.
//
// Wire format
// -----------
// The backend's ``ServoThreadStateResponse.errors`` array and the
// ``{type:"error", data:...}`` envelope both carry
// ``{kind, text, time}``. ``kind`` is preserved verbatim. ``time``
// is the ISO-8601 stamp the backend applied on receipt — useful
// when the bounded history is replayed after a reconnect.
//
// Keeping this table static (rather than fetching it from a
// backend endpoint) means it ships with the bundle, has zero
// latency on the error path, and tree-shakes cleanly. Adding new
// kinds is a one-line edit + a translation test in
// ``frontend/tests/test-linuxcnc-errors.mjs``.

export type LinuxCNCErrorKind = number;

/** A single LinuxCNC ``error_channel.poll()`` payload. */
export interface LinuxCNCErrorPayload {
    kind?: LinuxCNCErrorKind | null;
    text?: string | null;
    time?: string | null;
    /**
     * Backend classification of ``kind``: ``info`` for an operator
     * message (G-code ``(MSG, ...)``), ``error`` for a fault
     * (``(ABORT, ...)``). Missing on older backends — treat as error.
     */
    severity?: "error" | "info" | null;
}

/** True for an operator message (``(MSG, ...)``) rather than a fault. */
export function isLinuxCNCMessage(payload: LinuxCNCErrorPayload | null | undefined): boolean {
    return payload?.severity === "info";
}

/** Entry in the human-readable translation table. */
export interface LinuxCNCErrorEntry {
    /** Short operator-facing label, e.g. "Spindle error". */
    name: string;
    /**
     * Slightly longer hint that goes on the toast / log line,
     * e.g. "Spindle controller reported a fault — check VFD".
     */
    description: string;
}

/**
 * Single source of truth for every known LinuxCNC NML error class.
 *
 * Source: ``src/emc/nml_intf/emc.hh`` in the LinuxCNC tree, plus
 * the ``NML_ERROR`` / ``OPERATOR_ERROR`` family the python-linuxcnc
 * ``error_channel`` actually returns in practice. The categories
 * mirror the LinuxCNC subsystems that own the relevant error
 * channel, so an operator can usually guess where to look first
 * (e.g. ``EMC_INTERP_TYPE`` → G-code / interpreter).
 */
export const LINUXCNC_ERROR_KINDS: Readonly<Record<number, LinuxCNCErrorEntry>> =
    Object.freeze({
        // ─── python-linuxcnc error-channel kinds ──────────────────────
        // The values ``linuxcnc.NML_ERROR`` ... ``OPERATOR_DISPLAY``
        // carry (the NML message type ids). ``(MSG, ...)`` in G-code
        // arrives as 13, ``(ABORT, ...)`` as 11.
        1: {
            name: "NML error",
            description: "Internal NML channel error reported by the task controller.",
        },
        2: {
            name: "NML text",
            description: "Informational message from the task controller.",
        },
        3: {
            name: "NML display",
            description: "Display-only message from the task controller.",
        },
        11: {
            name: "Operator error",
            description: "Error raised for the operator — e.g. G-code (ABORT, ...) or a HAL component fault.",
        },
        12: {
            name: "Operator text",
            description: "Informational operator message (not an error).",
        },
        13: {
            name: "Operator message",
            description: "Operator message — e.g. G-code (MSG, ...). Not an error.",
        },

        // ─── Legacy / custom codes used by this UI's mock + history ────
        // The mock's ``push_error`` defaults ``kind=11`` and the
        // LinuxCNC daemon historically re-uses a couple of small
        // integers for trajectory / soft-limit faults. Map the
        // common ones explicitly so the table does not say
        // "Unknown" for an entry the operator sees daily.
        100: {
            name: "Soft limit exceeded",
            description:
                "Move would exceed a configured soft limit — check program coordinates vs. axis limits.",
        },
        101: {
            name: "Hard limit hit",
            description:
                "Hardware limit switch activated — clear the limit, re-home the affected joint.",
        },
        102: {
            name: "Joint follow error",
            description:
                "Joint fell behind its commanded position — check amp / encoder / mechanical binding.",
        },
    });

/**
 * Default entry returned when the upstream ``kind`` is not in the
 * translation table. Keeps the message structure stable (every
 * operator-facing line still has ``name`` + ``description``) while
 * surfacing the raw integer so a power-user can grep the source.
 */
const UNKNOWN_KIND: LinuxCNCErrorEntry = Object.freeze({
    name: "Unknown LinuxCNC error",
    description: "Unrecognised LinuxCNC error class — see the raw text and kind code below.",
});

/**
 * Return the translation table entry for ``kind`` (or a stable
 * "unknown" fallback when the code is not registered).
 *
 * Pure / referentially transparent — safe to call from any UI
 * layer, including the toast pipeline and the console replay
 * loop, without memoisation.
 */
export function lookupLinuxCNCError(kind: LinuxCNCErrorKind): LinuxCNCErrorEntry {
    if (typeof kind !== "number" || !Number.isFinite(kind)) {
        return UNKNOWN_KIND;
    }
    return LINUXCNC_ERROR_KINDS[kind] ?? UNKNOWN_KIND;
}

/**
 * Render one ``{kind, text, time}`` error entry into a single
 * operator-facing line. The format mirrors what AXIS used to
 * show in its error pane and is designed to be both human-readable
 * and grep-friendly:
 *
 *     [Spindle error #12] VFD reported a fault — clearance required
 *
 * Falls back gracefully when ``kind`` is missing (the field is
 * optional in the OpenAPI schema because real LinuxCNC's
 * ``stat.errors`` is a list of plain strings).
 */
export function formatLinuxCNCError(error: LinuxCNCErrorPayload | null | undefined): string {
    const text = (error?.text ?? "").toString().trim() || "(no message)";
    // An operator message reads as itself — no "[Operator message #13]"
    // prefix around "Bore Diameter is: 20.01".
    if (isLinuxCNCMessage(error)) return text;
    if (error?.kind === undefined || error.kind === null) {
        return text;
    }
    const entry = lookupLinuxCNCError(error.kind);
    const code = `#${error.kind}`;
    if (entry.name === UNKNOWN_KIND.name) {
        return `[LinuxCNC ${code}] ${text}`;
    }
    return `[${entry.name} ${code}] ${text}`;
}

/**
 * Type guard that narrows ``unknown`` to a ``LinuxCNCErrorPayload``
 * shape. The WS envelope's ``data`` is intentionally typed as
 * ``unknown`` so a malformed frame cannot crash the loop; callers
 * that need the typed fields use this guard before accessing
 * ``kind`` / ``text`` / ``time``.
 */
export function isLinuxCNCError(value: unknown): value is LinuxCNCErrorPayload {
    if (!value || typeof value !== "object") return false;
    const candidate = value as Record<string, unknown>;
    const kindOk =
        candidate.kind === undefined ||
        candidate.kind === null ||
        typeof candidate.kind === "number";
    const textOk =
        candidate.text === undefined ||
        candidate.text === null ||
        typeof candidate.text === "string";
    const timeOk =
        candidate.time === undefined ||
        candidate.time === null ||
        typeof candidate.time === "string";
    const severityOk =
        candidate.severity === undefined ||
        candidate.severity === null ||
        candidate.severity === "error" ||
        candidate.severity === "info";
    return kindOk && textOk && timeOk && severityOk;
}
