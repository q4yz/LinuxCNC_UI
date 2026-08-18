import {FileEntry} from "../entities/files";
import {WireFile} from "../entities/files/FileEntry";


/**
 * Convert a single wire row into a `FileEntry`.
 *
 * @param wire The incoming API payload
 * @returns A validated FileEntry instance, or null if the payload is invalid
 */
export function toFileEntry(wire: WireFile | null | undefined): FileEntry | null {
  if (!wire || typeof wire !== "object") return null;

  const name =
      typeof wire.name === "string"
          ? wire.name
          : typeof wire.filename === "string"
              ? wire.filename
              : null;

  if (!name) return null;

  return new FileEntry({
    name,
    path: typeof wire.path === "string" ? wire.path : name,
    kind: typeof wire.kind === "string" ? wire.kind : "file",
    sizeBytes: Number(wire.size_bytes ?? wire.sizeBytes) || 0,
    parent: typeof wire.parent === "string" ? wire.parent : null,
    modified: typeof wire.modified === "string" ? wire.modified : null,
    readOnly: Boolean(wire.read_only ?? wire.readOnly),
  });
}

/**
 * Convert an array of wire rows into an array of strictly typed FileEntries.
 *
 * @param arr Array of wire payloads
 * @returns An array of successfully parsed FileEntry objects
 */
export function toFileListing(arr: WireFile[] | null | undefined): FileEntry[] {
  if (!Array.isArray(arr)) return [];

  return arr
      .map((entry) => toFileEntry(entry))
      .filter((e): e is FileEntry => e !== null);
}