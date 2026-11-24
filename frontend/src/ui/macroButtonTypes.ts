// Shared shape of a configurable macro button (DRO rows, toolpath
// viewer slots). Persisted as the ``machine.macro_buttons`` UI setting
// (``settings/definitions/machine``); rendered by ``MacroButton.vue``,
// edited by ``MacroButtonEditor.vue``.

/**
 * One row of the persistent macro-button list. ``slot`` is the stable
 * panel position; the other fields are optional so a half-filled row
 * never crashes a host.
 */
export interface MacroButtonDescriptor {
  slot: string;
  enabled?: boolean;
  name?: string;
  icon?: string;
  /** The macro / NGC name — for kind ``component`` the panel id
   * (``pagePanels.PANELS``) the button opens in a floating window, for kind
   * ``output`` the output it controls (``outputTargets``: ``out:<id>``,
   * ``fan:<id>``, ``led:<id>``). */
  macroName?: string;
  macroKind?: "macro" | "ngc" | "component" | "output";
}

/** One host-declared button position (``id`` unique per host). */
export interface MacroButtonSlotDef {
  id: string;
  label?: string;
}

/** Coerce stored data into ``MacroButtonDescriptor[]`` (drops malformed rows). */
export function normaliseMacroButtons(raw: unknown): MacroButtonDescriptor[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (row: unknown): row is MacroButtonDescriptor =>
      row !== null && typeof row === "object" && typeof (row as Record<string, unknown>).slot === "string",
  );
}

/** What an enabled button still lacks before it is shown: a label
 * (``name``, not only blanks) and an action (``macroName``). A button
 * with a problem is flagged red in the editor and never rendered (#126). */
export interface MacroButtonProblems {
  missingLabel: boolean;
  missingAction: boolean;
}

export function macroButtonProblems(row: Pick<MacroButtonDescriptor, "name" | "macroName">): MacroButtonProblems {
  return {
    missingLabel: (row.name ?? "").trim().length === 0,
    missingAction: (row.macroName ?? "").length === 0,
  };
}

/** An enabled button with a label and an action: the only one a host shows. */
export function isMacroButtonComplete(row: MacroButtonDescriptor | null | undefined): boolean {
  if (row == null || row.enabled !== true) return false;
  const p = macroButtonProblems(row);
  return !p.missingLabel && !p.missingAction;
}
