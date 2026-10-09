import type { FileEntryResponse } from "../../generated/api/models/FileEntryResponse";
import { FileEntry } from "../entities/files";

/**
 * Convert one `FileEntryResponse` (the shared record every file
 * listing endpoint returns) into a `FileEntry`.
 *
 * @returns the entry, or `null` for a payload without a name
 */
export function toFileEntry(wire: FileEntryResponse | null | undefined): FileEntry | null {
  if (!wire || typeof wire !== "object" || typeof wire.name !== "string" || !wire.name) {
    return null;
  }
  return new FileEntry({
    name: wire.name,
    path: wire.path,
    kind: wire.kind,
    sizeBytes: Number(wire.size_bytes) || 0,
    parent: wire.parent ?? null,
    modified: wire.modified ?? null,
    readOnly: wire.read_only,
    hasMarker: wire.has_marker,
  });
}

/** Convert a listing; malformed rows are dropped. */
export function toFileListing(arr: FileEntryResponse[] | null | undefined): FileEntry[] {
  if (!Array.isArray(arr)) return [];
  return arr
    .map((entry) => toFileEntry(entry))
    .filter((e): e is FileEntry => e !== null);
}
