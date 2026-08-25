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
        // ─── NML channel classes (python-linuxcnc surface) ─────────────
        0: {
            name: "Unspecified error",
            description:
                "LinuxCNC reported an error without a known class. The raw text follows.",
        },
        1: {
            name: "NML error",
            description: "Internal NML channel error reported by the task controller.",
        },
        2: {
            name: "Operator error",
            description: "Operator-facing error surfaced from a HAL component or the task.",
        },
        3: {
            name: "Operator text",
            description: "Informational operator message (not necessarily an error).",
        },
        4: {
            name: "Operator display",
            description: "Display-only message — usually safe to ignore.",
        },

        // ─── EMC subsystem error classes ──────────────────────────────
        5: {
            name: "System error",
            description: "Generic LinuxCNC system / EMC subsystem fault.",
        },
        6: {
            name: "Trajectory planner error",
            description:
                "Trajectory planner rejected a move — check feed / accel limits and joint constraints.",
        },
        7: {
            name: "Task error",
            description:
                "Task controller reported a fault (MDI / interpreter coordination, mode switches).",
        },
        8: {
            name: "Motion controller error",
            description:
                "Motion controller reported a fault — check joint enable, follower error and amp faults.",
        },
        9: {
            name: "Interpreter error",
            description:
                "RS274NGC interpreter reported a G-code problem (bad syntax, illegal modal combination).",
        },
        10: {
            name: "I/O controller error",
            description:
                "I/O controller flagged an error — check HAL signal wiring and digital inputs.",
        },
        11: {
            name: "Tool changer error",
            description:
                "Tool changer failed — verify tool-prep / tool-change sequence and HAL signals.",
        },
        12: {
            name: "Spindle error",
            description:
                "Spindle controller reported a fault — check VFD / spindle drive state and HAL pins.",
        },
        13: {
            name: "Coolant error",
            description:
                "Coolant controller flagged an error — verify flood / mist HAL signals.",
        },
        14: {
            name: "Lubrication error",
            description:
                "Lube subsystem reported a fault — check lube pump / oil-level sensor.",
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
    return kindOk && textOk && timeOk;
}
