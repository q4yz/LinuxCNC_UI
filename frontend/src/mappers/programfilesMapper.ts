import {ProgramFile} from "../entities/progress";
import {WireFile} from "../entities/files/FileEntry";

/**
 * Convert a single wire row into a `ProgramFile`.
 *
 * @param wire The incoming API payload
 * @returns A validated ProgramFile instance, or null if the payload is invalid
 */
export function toProgramFile(wire: WireFile | null | undefined): ProgramFile | null {
    if (!wire || typeof wire !== "object") return null;

    const name =
        typeof wire.name === "string"
            ? wire.name
            : typeof wire.filename === "string"
                ? wire.filename
                : null;

    if (!name) return null;

    return new ProgramFile({
        name,
        path: typeof wire.path === "string" ? wire.path : name,
        kind: typeof wire.kind === "string" ? wire.kind : "file",
        sizeBytes: Number(wire.size_bytes ?? wire.sizeBytes) || 0,
        modified: typeof wire.modified === "string" ? wire.modified : null,
    });
}

/**
 * Convert an array of wire rows into an array of strictly typed ProgramFiles.
 *
 * @param arr Array of wire payloads
 * @returns An array of successfully parsed ProgramFile objects
 */
export function toProgramFileListing(arr: WireFile[] | null | undefined): ProgramFile[] {
    if (!Array.isArray(arr)) return [];

    return arr
        .map((entry) => toProgramFile(entry))
        .filter((e): e is ProgramFile => e !== null);
}