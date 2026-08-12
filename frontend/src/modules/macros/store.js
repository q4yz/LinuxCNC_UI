// Macros module Pinia store. Fronts ``ModulesMacrosService`` (the
// OpenAPI-generated client) with state + cached payload + convenience
// actions. Three ``kind`` values share the same router, distinguished
// by the ``?kind=`` query parameter:
//
//   ``"macro"`` — ``<repo>/macros/<name>.macro`` (custom G-code +
//                  python-block payloads). Parsed + dispatched as
//                  per-line MDI on the dashboard "Run" button.
//   ``"ngc"``   — ``<repo>/macros/<name>.ngc`` (LinuxCNC native
//                  O-word subroutine). No "Run" affordance — the
//                  ``program_open`` flow owns runtime; the UI only
//                  manages the file.
//   ``"mcode"`` — ``<repo>/machine_config/m_codes/<name>`` (bare
//                  ``M<num>`` file in the canonical LinuxCNC
//                  ``USER_M_PATH`` range, M100..M199). No "Run"
//                  affordance either — the interpreter dispatches
//                  these on ``M<num>`` MDI; the UI manages.
//
// List storage is **per-kind**: each kind owns its own ``ref`` so
// that ``loadList(kind)`` never empties the others. The previous
// implementation funnelled every listing through a single ``macros``
// array; ``loadList('mcode')`` would clobber the macro / ngc rows
// that ``MacroPanel`` was rendering. Splitting the container fixes
// that race without resorting to merge-instead-of-replace logic.
//
// All HTTP calls go through the generated client so we keep types in
// sync with the OpenAPI schema. Errors are routed to
// ``useConsoleStore``, which the operator sees in the dashboard's
// persistent log.
//
// ``useConsoleStore`` and ``useMachineStore`` are instantiated lazily
// inside each action to dodge the cross-store import cycle described
// in ``.agent/LESSONS_LEARNED.md`` § 2.4.

import { defineStore } from "pinia";
import { reactive, ref } from "vue";

import {
  ModulesMachineService,
  ModulesMacrosService,
} from "../../../generated/api/index.ts";
import manifest from "./manifest.js";
import { useConsoleStore } from "../../stores/console.js";
import { useMachineStore } from "../../stores/machineStoreShim.js";
import { describeError as describeErrorShared } from "../../core/error-format.js";
import { parseMacro, validateMacroKindName } from "./parser.js";

// Canonical kind constants. Must agree with the backend's
// ``VALID_KINDS`` enum (``backend/modules/macros/router.py``).
export const MACRO_KIND = Object.freeze({
  MACRO: "macro",
  NGC: "ngc",
  MCODE: "mcode",
});

const STORE_ID = `module_${manifest.id}`;

/**
 * Wrapper around :func:`core/error-format.js` ``describeError`` that
 * keeps the legacy "Unknown error" fallback for any falsy input so
 * existing ``useConsoleStore().error(...)`` calls don't regress to
 * empty strings. The shared helper handles the same envelope shapes
 * (``error.body.error.message`` for compile-time validation,
 * ``error.body.detail`` for plain FastAPI ``HTTPException``,
 * ``error.message`` for everything else) so a future envelope shape
 * change lives in one place.
 */
const describeError = (error) =>
  describeErrorShared(error) || "Unknown error";

/**
 * Split a static block into individual MDI commands. A block may
 * contain one or several newlines (the parser concatenates
 * consecutive non-``{...}`` content); LinuxCNC wants one command
 * per MDI call so the dashboard progress stream stays meaningful.
 *
 * Blank lines and pure-comment lines are skipped.
 *
 * @param {string} content
 * @returns {string[]}
 */
function splitStaticBlock(content) {
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/**
 * Normalise ``""`` → ``"\n"``. FastAPI rejects a zero-byte
 * ``text/plain`` body with ``422`` so an empty editor would
 * otherwise fail to save. Mirrors the same escape the macros
 * dashboard already uses for ``.macro`` files.
 *
 * @param {string} body
 * @returns {string}
 */
function normalizeEmpty(body) {
  return body.length === 0 ? "\n" : body;
}

/**
 * Translate the generated client's ``MacroListResponse.macros`` into
 * a plain array of ``{ name, kind, size_bytes }`` records. The
 * generated ``MacroListItem`` is structurally identical so we keep
 * the field names the same.
 *
 * @param {unknown} response
 * @returns {Array<{name: string, kind: string, size_bytes: number}>}
 */
function normalizeListEntries(response) {
  const raw = response?.macros;
  return Array.isArray(raw) ? raw : [];
}

export const useMacrosStore = defineStore(STORE_ID, () => {
  // --- reactive state ------------------------------------------ //

  /**
   * Per-kind listing refs. Each ``loadList(kind)`` writes into the
   * matching container only; the others stay populated. Mounting
   * order no longer matters — ``McodePanel`` mounting after
   * ``MacroPanel`` no longer empties the macro / ngc listings
   * (the original bug).
   *
   * Dashboard panels subscribe via ``storeToRefs(store)`` and
   * pick the right ref (or join ``macroFiles`` + ``ngcFiles`` for
   * the legacy MacroPanel) directly.
   */
  const macroFiles = ref([]);
  const ngcFiles = ref([]);
  const mcodeFiles = ref([]);

  /**
   * Cache of fetched payloads. Keyed by ``<kind>:<name>`` so the
   * dashboard's "Run" path on ``macro`` rows doesn't collide with
   * the editor opening the same name under a different kind.
   */
  const contents = reactive({});

  /** UI flag — true while a list mutation / delete / save is in flight. */
  const isBusy = ref(false);

  /** Last error surfaced by an action (or ``null``). */
  const lastError = ref(/** @type {string|null} */ (null));

  /** Map of kind → listing ref. Localised so ``loadList(kind)``
   *  can dispatch via a single table lookup.
   */
  const listRefs = {
    [MACRO_KIND.MACRO]: macroFiles,
    [MACRO_KIND.NGC]: ngcFiles,
    [MACRO_KIND.MCODE]: mcodeFiles,
  };

  function listRefFor(kind) {
    const ref = listRefs[kind];
    if (!ref) {
      throw new Error(
        `macros store: unknown kind ${JSON.stringify(kind)}`,
      );
    }
    return ref;
  }

  // --- list / read / write / delete ---------------------------- //

  /**
   * Fetch the listing for a single ``kind``. Writes into the
   * matching per-kind container only — calling this repeatedly
   * with different kinds never empties the others.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @returns {Promise<Array<{name: string, kind: string, size_bytes: number}>>}
   */
  async function loadList(kind = MACRO_KIND.MACRO) {
    const target = listRefFor(kind);
    try {
      const response = await ModulesMacrosService.listMacros(kind);
      // Tag every row with its kind so the dashboard panels can
      // join the macro + ngc refs without losing the source.
      const entries = normalizeListEntries(response).map((row) => ({
        ...row,
        kind,
      }));
      target.value = entries;
      return target.value;
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(
        `Failed to list macros (${kind}): ${lastError.value}`,
      );
      return [];
    }
  }

  /**
   * Reload all three listings concurrently. The per-kind
   * containers stay isolated so this is safe even with mount /
   * unmount races on the dashboard.
   *
   * @returns {Promise<Array<{name: string, kind: string, size_bytes: number}>>}
   */
  async function loadAll() {
    await Promise.all([
      loadList(MACRO_KIND.MACRO),
      loadList(MACRO_KIND.NGC),
      loadList(MACRO_KIND.MCODE),
    ]);
    return [
      ...macroFiles.value,
      ...ngcFiles.value,
      ...mcodeFiles.value,
    ];
  }

  /** Cache key for the contents map. */
  function cacheKey(kind, name) {
    return `${kind}:${name}`;
  }

  /**
   * Fetch a macro's raw payload, cache it, and return the string.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   * @returns {Promise<string|null>} ``null`` when the fetch failed.
   */
  async function readMacro(kind, name) {
    validateMacroKindName(kind, name);
    try {
      const text = await ModulesMacrosService.readMacro(name, kind);
      const payload =
        typeof text === "string" ? text : text == null ? "" : String(text);
      contents[cacheKey(kind, name)] = payload;
      return payload;
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(
        `Failed to read macro '${name}' (${kind}): ${lastError.value}`,
      );
      return null;
    }
  }

  /**
   * Cached lookup; falls back to a network fetch on miss. The
   * ``(kind, name)`` pair is the cache key so the same macro name
   * under different kinds does not collide.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   * @returns {Promise<string|null>}
   */
  async function ensureMacroContent(kind, name) {
    const cached = contents[cacheKey(kind, name)];
    if (typeof cached === "string") return cached;
    return readMacro(kind, name);
  }

  /**
   * Persist ``body`` to ``<kind>:<name>`` (creating or overwriting).
   * Refreshes the matching per-kind listing in place — the other
   * two listings stay warm. ``loadList`` would be a heavier
   * round-trip; the row we just wrote is already known.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   * @param {string} body
   * @returns {Promise<boolean>} Success flag.
   */
  async function saveMacro(kind, name, body) {
    validateMacroKindName(kind, name);
    const safeBody = normalizeEmpty(body);
    if (typeof safeBody !== "string") {
      lastError.value = "Macro body must be a string.";
      useConsoleStore().error(lastError.value);
      return false;
    }
    isBusy.value = true;
    try {
      await ModulesMacrosService.writeMacro(name, safeBody, kind);
      contents[cacheKey(kind, name)] = safeBody;
      useConsoleStore().success(
        `Saved macro '${name}' (${kind}, ${safeBody.length} bytes).`,
      );
      const target = listRefFor(kind);
      const size_bytes =
        typeof safeBody === "string"
          ? new Blob([safeBody]).size
          : 0;
      const row = { name, kind, size_bytes };
      const idx = target.value.findIndex((entry) => entry.name === name);
      if (idx === -1) target.value.push(row);
      else target.value.splice(idx, 1, row);
      return true;
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(
        `Failed to save macro '${name}' (${kind}): ${lastError.value}`,
      );
      return false;
    } finally {
      isBusy.value = false;
    }
  }

  /**
   * Remove a macro from disk and drop its cached content. The
   * matching per-kind listing is patched in place; the other two
   * listings stay warm.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   * @returns {Promise<boolean>}
   */
  async function deleteMacro(kind, name) {
    validateMacroKindName(kind, name);
    isBusy.value = true;
    try {
      await ModulesMacrosService.deleteMacro(name, kind);
      delete contents[cacheKey(kind, name)];
      useConsoleStore().success(`Deleted macro '${name}' (${kind}).`);
      const target = listRefFor(kind);
      const idx = target.value.findIndex((entry) => entry.name === name);
      if (idx !== -1) target.value.splice(idx, 1);
      return true;
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(
        `Failed to delete macro '${name}' (${kind}): ${lastError.value}`,
      );
      return false;
    } finally {
      isBusy.value = false;
    }
  }

  // --- execute ------------------------------------------------- //

  /**
   * "Run" a ``macro`` row. Reads its content, parses it into
   * blocks, and dispatches each ``static`` block as one MDI
   * command per non-blank line via
   * ``ModulesMachineService.runMdiCommand``. ``python`` blocks
   * are surfaced to the console as warnings — the backend
   * interpreter is not implemented yet, so we explicitly do not
   * feed them to the hardware layer.
   *
   * Scoped to ``kind="macro"`` only — ``ngc`` subroutines are
   * dispatched by the controller via ``program_open`` (not MDI),
   * and ``mcode`` files are dispatched by the interpreter on
   * ``M<num>`` MDI. Neither surface has a "Run" button.
   *
   * Guarded by ``isEstopActive`` so an E-Stop block aborts the run
   * before any MDI is dispatched.
   *
   * @param {string} name
   * @returns {Promise<{staticDispatched: number, pythonSkipped: number}>}
   */
  async function runMacro(name) {
    return runMacroOfKind(MACRO_KIND.MACRO, name);
  }

  /**
   * Generic runner; kept exported so a future release can flip the
   * dashboard to also dispatch ``ngc`` files (or add a "dry-run"
   * code path for ``mcode``).
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   */
  async function runMacroOfKind(kind, name) {
    if (kind !== MACRO_KIND.MACRO) {
      useConsoleStore().warning(
        `Running ${kind} files from the UI is not supported — ` +
          "they are dispatched by the controller / interpreter.",
      );
      return { staticDispatched: 0, pythonSkipped: 0 };
    }
    validateMacroKindName(kind, name);
    const consoleStore = useConsoleStore();

    const machine = useMachineStore();
    if (machine.isEstopActive) {
      consoleStore.error(
        "Cannot run macros while the machine is in E-Stop.",
      );
      return { staticDispatched: 0, pythonSkipped: 0 };
    }

    const body = await ensureMacroContent(kind, name);
    if (body == null) return { staticDispatched: 0, pythonSkipped: 0 };

    let blocks;
    try {
      blocks = parseMacro(body);
    } catch (error) {
      consoleStore.error(
        `Macro '${name}' failed to parse: ${error instanceof Error ? error.message : String(error)}`,
      );
      return { staticDispatched: 0, pythonSkipped: 0 };
    }

    let staticDispatched = 0;
    let pythonSkipped = 0;
    consoleStore.info(`Running macro '${name}' (${blocks.length} block(s)).`);

    for (let index = 0; index < blocks.length; index++) {
      const block = blocks[index];
      if (block.type === "python") {
        pythonSkipped += 1;
        consoleStore.warning(
          `Macro '${name}' block #${index + 1}: python block skipped — interpreter not implemented yet.`,
        );
        continue;
      }

      const lines = splitStaticBlock(block.content);
      for (const line of lines) {
        // Mid-run safety re-check: an E-Stop issued during dispatch
        // must abort the remaining commands instead of feeding them
        // to a dead machine.
        if (machine.isEstopActive) {
          consoleStore.error(
            `Macro '${name}' aborted: machine entered E-Stop during dispatch.`,
          );
          return { staticDispatched, pythonSkipped };
        }

        try {
          await ModulesMachineService.runMdiCommand({ command: line });
          staticDispatched += 1;
        } catch (error) {
          consoleStore.error(
            `Macro '${name}' MDI '${line}' failed: ${describeError(error)}`,
          );
          // Continue with the next line — a single failed MDI does
          // not invalidate the remaining commands.
        }
      }
    }

    consoleStore.success(
      `Macro '${name}' dispatched ${staticDispatched} MDI command(s); skipped ${pythonSkipped} python block(s).`,
    );
    return { staticDispatched, pythonSkipped };
  }

  // --- public surface ------------------------------------------ //

  return {
    MACRO_KIND,
    macroFiles,
    ngcFiles,
    mcodeFiles,
    contents,
    isBusy,
    lastError,
    loadList,
    loadAll,
    readMacro,
    ensureMacroContent,
    saveMacro,
    deleteMacro,
    runMacro,
    runMacroOfKind,
  };
});

export default useMacrosStore;
