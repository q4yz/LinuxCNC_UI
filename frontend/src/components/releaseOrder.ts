// Release tags (no imports — the node tests load it directly): which way
// installing one moves from the running version.

/** ``v1.2.10`` / ``1.2.0-rc1`` -> [1, 2, 10] / [1, 2, 0]; null for anything else. */
export function versionParts(tag: string | null | undefined): number[] | null {
  const match = /^v?(\d+(?:\.\d+)*)/.exec(tag ?? "");
  return match ? match[1].split(".").map(Number) : null;
}

/** -1: ``tag`` is older than ``current`` (going back), 0: the same, 1: newer, null: unknown. */
export function compareRelease(tag: string, current: string | null | undefined): -1 | 0 | 1 | null {
  if (current && tag === current) return 0;
  const a = versionParts(tag);
  const b = versionParts(current);
  if (!a || !b) return null;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    if (d) return d < 0 ? -1 : 1;
  }
  // Same numbers: a pre-release ("-rc1") is before the release itself.
  const preA = tag.includes("-");
  const preB = (current ?? "").includes("-");
  return preA === preB ? 0 : preA ? -1 : 1;
}
