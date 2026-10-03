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
  macroName?: string;
  macroKind?: "macro" | "ngc";
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
