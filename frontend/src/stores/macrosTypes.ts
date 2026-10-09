// Shared types for the macros module. Centralised here so the
// store, the parser, the facade, and every Vue component pull
// from the same vocabulary. ``MACRO_KIND`` itself lives next to
// the store that owns the runtime shape (and the structural
// tests expect to find ``Object.freeze`` there).

import type { FileEntry } from "../entities/files";

export type MacroKind = "macro" | "ngc" | "mcode";

/**
 * One listed macro: its own identity (``name`` without extension +
 * ``kind``, what the macro endpoints address it by) plus the shared
 * file record every file listing carries (size, change date, ...).
 */
export interface MacroEntry {
  name: string;
  kind: MacroKind;
  file: FileEntry;
}

/** A single block produced by ``parseMacro``. */
export interface MacroBlock {
  type: "static" | "python";
  content: string;
}

/**
 * Cache of fetched payloads keyed by ``<kind>:<name>``. Same shape
 * as the macros store's reactive ``contents`` record so the type
 * alias can be referenced from the store, the facade, and the
 * management panels.
 */
export type MacroContents = Record<string, string>;

/** Counter payload returned by ``runMacro`` / ``runMacroOfKind``. */
export interface MacroRunCounters {
  staticDispatched: number;
  pythonSkipped: number;
}

/** Discriminated UI shape for the last-run result line in ``MacroPanel``. */
export interface MacroLastRunResult extends MacroRunCounters {
  name: string;
}