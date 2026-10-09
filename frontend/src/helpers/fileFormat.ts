// Display helpers shared by every file list, so size and change date
// read the same everywhere (`FileEntry.sizeBytes` / `FileEntry.modified`).

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** `modified` (ISO-8601) as a short local date + time; "—" when unknown. */
export function formatFileDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
