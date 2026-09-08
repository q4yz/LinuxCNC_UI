// Folder tree for the HAL pin picker drawers.
//
// Real machines expose hundreds of pins as one flat list, which is
// hard to scan. HAL names are already hierarchical — every `.` is a
// natural boundary (`halui.axis.z.step` = `halui` / `axis` / `z` /
// `step`) — so this builds a nested folder tree out of that instead
// of showing the flat list. The last segment is the pin itself; every
// segment before it is a folder.

import type { HalPin } from "./types";

export interface PinTreeLeaf {
  kind: "pin";
  segment: string;
  pin: HalPin;
}

export interface PinTreeFolder {
  kind: "folder";
  /** This folder's own name, e.g. "z". */
  segment: string;
  /** Full dotted path to this folder, e.g. "halui.axis.z". */
  path: string;
  children: PinTreeNode[];
}

export type PinTreeNode = PinTreeLeaf | PinTreeFolder;

/** `"halui.axis.z.step"` -> `"step"` — the piece the operator matches on. */
export function lastSegment(fullName: string): string {
  const parts = fullName.split(".").filter(Boolean);
  return parts[parts.length - 1] ?? fullName;
}

/**
 * Build the folder tree for `pins`. Returns the (unnamed) root
 * folder — render `root.children`, not the root itself.
 *
 * A pin whose name collides with an existing folder segment at the
 * same level (rare — e.g. a bare `foo.bar` pin alongside a deeper
 * `foo.bar.baz` one) renders as a sibling leaf next to that folder
 * rather than being dropped; HAL naming doesn't guarantee otherwise.
 */
export function buildPinTree(pins: HalPin[]): PinTreeFolder {
  const root: PinTreeFolder = { kind: "folder", segment: "", path: "", children: [] };

  for (const pin of pins) {
    const parts = pin.fullName.split(".").filter(Boolean);
    if (parts.length === 0) continue;

    let node = root;
    for (let i = 0; i < parts.length; i += 1) {
      const segment = parts[i];
      if (i === parts.length - 1) {
        node.children.push({ kind: "pin", segment, pin });
        break;
      }
      let child = node.children.find(
        (c): c is PinTreeFolder => c.kind === "folder" && c.segment === segment,
      );
      if (!child) {
        const path = node.path ? `${node.path}.${segment}` : segment;
        child = { kind: "folder", segment, path, children: [] };
        node.children.push(child);
      }
      node = child;
    }
  }

  sortChildren(root);
  return root;
}

function sortChildren(folder: PinTreeFolder): void {
  folder.children.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
    return a.segment.localeCompare(b.segment, undefined, { numeric: true });
  });
  for (const child of folder.children) {
    if (child.kind === "folder") sortChildren(child);
  }
}

/** Whether any pin inside `folder` (at any depth) ends in `suffix`. */
export function folderContainsSuffix(folder: PinTreeFolder, suffix: string | null): boolean {
  if (!suffix) return false;
  for (const child of folder.children) {
    if (child.kind === "pin") {
      if (lastSegment(child.pin.fullName) === suffix) return true;
    } else if (folderContainsSuffix(child, suffix)) {
      return true;
    }
  }
  return false;
}

/**
 * Folder paths that should render expanded without the operator
 * clicking anything: every folder is expanded while `expandAll` is
 * set (there's an active search — results are already filtered down,
 * so drilling manually just adds clicks), plus the ancestors of any
 * pin whose last segment equals `matchSuffix` regardless of search —
 * "pop open" the name-matched pins so they're visible immediately.
 */
export function collectAutoExpandPaths(
  pins: HalPin[],
  matchSuffix: string | null,
  expandAll: boolean,
): Set<string> {
  const paths = new Set<string>();
  if (!expandAll && !matchSuffix) return paths;

  for (const pin of pins) {
    const parts = pin.fullName.split(".").filter(Boolean);
    if (parts.length <= 1) continue;
    const isMatch = matchSuffix !== null && parts[parts.length - 1] === matchSuffix;
    if (!expandAll && !isMatch) continue;

    let acc = "";
    for (let i = 0; i < parts.length - 1; i += 1) {
      acc = acc ? `${acc}.${parts[i]}` : parts[i];
      paths.add(acc);
    }
  }
  return paths;
}
