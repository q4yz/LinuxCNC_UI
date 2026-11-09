// Pure helpers for dragging explorer entries (no imports — the node tests
// load them directly): where a drop moves an entry, and the list sorting
// of the G-code files table.

/** The drag's own data type: never "Files", so FileDropZone (uploads) ignores it. */
export const ENTRY_DRAG_TYPE = "application/x-linuxcnc-ui-entry";

function baseName(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

function parentOf(path: string): string {
  return path.split("/").filter(Boolean).slice(0, -1).join("/");
}

/**
 * The new path of ``source`` dropped on the folder ``targetDir`` ("" = the
 * root), or ``null`` when the drop does nothing / is not allowed: the same
 * folder it is in, onto itself, or a folder into its own subfolder.
 */
export function dropDestination(source: string, targetDir: string): string | null {
  const target = targetDir.replace(/^\/+|\/+$/g, "");
  if (parentOf(source) === target) return null;
  if (target === source || target.startsWith(`${source}/`)) return null;
  return [target, baseName(source)].filter(Boolean).join("/");
}

export type SortKey = "name" | "size" | "date";
export type SortDir = "asc" | "desc";

export interface SortableEntry {
  name: string;
  isFolder: boolean;
  sizeBytes?: number | null;
  modifiedMs: number;
}

/**
 * Folders first, then files, each by ``key`` (``childCount`` stands for a
 * folder's size); ties by name.
 */
export function sortEntries<T extends SortableEntry>(
  entries: readonly T[],
  key: SortKey,
  dir: SortDir,
  childCount: (entry: T) => number = () => 0,
): T[] {
  const sign = dir === "asc" ? 1 : -1;
  const value = (e: T): number | string =>
    key === "name" ? e.name.toLowerCase() : key === "size" ? (e.isFolder ? childCount(e) : e.sizeBytes ?? 0) : e.modifiedMs;
  return [...entries].sort((a, b) => {
    if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
    const va = value(a);
    const vb = value(b);
    if (va !== vb) return (va < vb ? -1 : 1) * sign;
    return a.name.localeCompare(b.name);
  });
}
