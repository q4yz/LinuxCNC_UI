// Files mapper. Translates the wire shapes from
// ``/api/v1/programs`` + ``/api/v1/modules/machineconfig/profiles/tree``
// + ``/api/v1/modules/machineconfig/staged`` + etc. into a
// single ``FileEntry`` entity.

import { FileEntry } from "../entities/files/FileEntry";

/**
 * Convert a single wire row into a ``FileEntry``.
 *
 * @param {object|null|undefined} wire
 * @returns {FileEntry|null}
 */
export function toFileEntry(wire) {
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
    sizeBytes:
      Number(wire.size_bytes ?? wire.sizeBytes) || 0,
    parent: typeof wire.parent === "string" ? wire.parent : null,
    modified: typeof wire.modified === "string" ? wire.modified : null,
    readOnly: Boolean(wire.read_only ?? wire.readOnly),
  });
}

/**
 * Convert an array of wire rows.
 *
 * @param {Array<object>|null|undefined} arr
 * @returns {FileEntry[]}
 */
export function toFileListing(arr) {
  if (!Array.isArray(arr)) return [];
  return arr.map((entry) => toFileEntry(entry)).filter((e) => e !== null);
}
