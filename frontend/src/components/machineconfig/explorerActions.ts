// Shared behaviour of the Profiles / Machines explorers' "⋮" menu:
// copy-name suggestion, the delete confirmation (with what a folder still
// contains) and the text download.

import { ModalButtonStyle, useConfirm } from "../../core/confirm";
import type { FileEntry } from "../../entities/files";

/** `a.cfg` -> `a-copy.cfg`, `dir` -> `dir-copy`; `-copy-2`, … when taken. */
export function suggestCopyPath(path: string, taken: ReadonlySet<string>): string {
  const slash = path.lastIndexOf("/");
  const dir = slash >= 0 ? path.slice(0, slash + 1) : "";
  const name = path.slice(slash + 1);
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  for (let n = 1; ; n++) {
    const candidate = `${dir}${stem}-copy${n === 1 ? "" : `-${n}`}${ext}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** What a folder still contains (all depths). */
export function folderContents(path: string, entries: readonly FileEntry[]): { files: number; folders: number } {
  const prefix = `${path}/`;
  let files = 0;
  let folders = 0;
  for (const entry of entries) {
    if (!entry.path.startsWith(prefix)) continue;
    if (entry.isFolder) folders++;
    else files++;
  }
  return { files, folders };
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * Ask before deleting. A folder with content may be deleted, but the
 * question says what goes with it; `recursive` tells the caller to
 * delete it with its content. `extraWarning` is appended (e.g. "this is
 * the default machine").
 */
export async function confirmDelete(
  entry: FileEntry,
  entries: readonly FileEntry[],
  extraWarning = "",
): Promise<{ confirmed: boolean; recursive: boolean }> {
  const { files, folders } = entry.isFolder ? folderContents(entry.path, entries) : { files: 0, folders: 0 };
  const recursive = files + folders > 0;
  const what = recursive
    ? `Folder ${entry.path} is not empty — it still contains ${[
        files ? plural(files, "file") : "",
        folders ? plural(folders, "folder") : "",
      ].filter(Boolean).join(" and ")}. Delete it with everything in it?`
    : `Delete ${entry.path}?`;
  const confirmed = await useConfirm({
    title: recursive ? "Delete folder and its content" : entry.isFolder ? "Delete folder" : "Delete file",
    question: `${what}${extraWarning ? ` ${extraWarning}` : ""} This cannot be undone.`,
    confirmButtonText: "Delete",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
  });
  return { confirmed, recursive };
}

/** Save `content` as a text file named `name`. */
export function downloadText(name: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.style.display = "none";
  // Firefox needs the anchor in the document.
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Safari still reads the URL right after click().
  setTimeout(() => URL.revokeObjectURL(url), 150);
}
