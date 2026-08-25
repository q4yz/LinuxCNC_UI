// Macros module Pinia store. Fronts ``macrosFacade`` (which wraps
// the OpenAPI-generated ``ModulesMacrosService``) with state +
// cached payload + convenience actions.
//
// Three ``kind`` values share the same router, distinguished by the
// ``?kind=`` query parameter:
//
//   ``"macro"`` — ``<repo>/macros/<name>.macro`` (custom G-code +
//                  python-block payloads). Runtime dispatch is a
//                  single ``POST /macros/{name}/start?kind=macro``
//                  call — the backend parses the body and feeds each
//                  static line into MDI. ``{python}`` blocks are
//                  skipped with a console-log warning (mirrors the
//                  pre-port behaviour). The JS parser in
//                  ``./parser.ts`` is still kept for the universal
//                  editor's preview only.
//   ``"ngc"``   — ``<repo>/macros/<name>.ngc`` (LinuxCNC native
//                  O-word subroutine). Dispatched via the same
//                  endpoint with ``?kind=ngc`` — the backend issues
//                  a single ``o<{name}> call`` MDI command.
//   ``"mcode"`` — ``<repo>/machine_config/m_codes/<name>`` (bare
//                  ``M<num>`` file in the canonical LinuxCNC
//                  ``USER_M_PATH`` range, M100..M199). No "Run"
//                  affordance — the interpreter dispatches these on
//                  ``M<num>`` MDI; the UI only manages the file.
//
// List storage is **per-kind**: each kind owns its own ``ref`` so
// that ``loadList(kind)`` never empties the others. The previous
// implementation funnelled every listing through a single ``macros``
// array; ``loadList('mcode')`` would clobber the macro / ngc rows
// that ``MacroPanel`` was rendering. Splitting the container fixes
// that race without resorting to merge-instead-of-replace logic.
//
// Every manual-write action (``saveMacro``, ``deleteMacro``,
// ``runMacro``, ``runMacroOfKind``) returns a ``Promise<CommandResult>``
// so the UI layer has a uniform response; failures are routed
// through ``reportCommandFailure``. Reads keep their legacy return
// shapes (``string|null`` for ``readMacro`` / ``ensureMacroContent``,
// array for ``loadList`` / ``loadAll``).
//
// ``useConsoleStore`` and ``useMachineStore`` are instantiated lazily
// inside each action to dodge the cross-store import cycle described
// in ``.agent/LESSONS_LEARNED.md`` § 2.4.

import { defineStore } from "pinia";
import { reactive, ref } from "vue";

import { macrosFacade } from "../../facades/macrosFacade";
import manifest from "./manifest";
import { useConsoleStore } from "../../stores/console";
import { useMachineStore } from "../../stores/machine";
import {
  describeError as describeErrorShared,
  errorStatus,
  reportCommandFailure,
} from "../../core/error-format";
import { CommandResult } from "../../entities/common/CommandResult";
import { validateMacroKindName } from "./parser";

// Canonical kind constants. Must agree with the backend's
// ``VALID_KINDS`` enum (``backend/routers/macros.py``).
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

/**
 * Builder for the legacy ``{ staticDispatched, pythonSkipped }``
 * counter shape historically returned by ``runMacro`` /
 * ``runMacroOfKind``. Encoded as JSON in ``CommandResult.message``
 * so existing dashboard widgets that read the counters keep their
 * input — newer code should branch on ``result.failed`` instead.
 */
function counterPayload(dispatched, skipped) {
  return JSON.stringify({ staticDispatched: dispatched, pythonSkipped: skipped });
}

function failureFromLegacy(reason, commandId) {
  return CommandResult.failure(reason, {
    commandId,
    statusCode: null,
  });
}

function failureFromError(error, commandId) {
  return CommandResult.failure(describeError(error), {
    commandId,
    statusCode: errorStatus(error),
  });
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

  // --- list / read (no CommandResult — these are reads) -------- //

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
      const response = await macrosFacade.list(kind);
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
      const text = await macrosFacade.read(name, kind);
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

  // --- write / run (CommandResult surface) -------------------- //

  /**
   * Persist ``body`` to ``<kind>:<name>`` (creating or overwriting).
   * Refreshes the matching per-kind listing in place — the other
   * two listings stay warm. ``loadList`` would be a heavier
   * round-trip; the row we just wrote is already known.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   * @param {string} body
   * @returns {Promise<CommandResult>}
   */
  async function saveMacro(kind, name, body): Promise<CommandResult> {
    validateMacroKindName(kind, name);
    const safeBody = normalizeEmpty(body);
    if (typeof safeBody !== "string") {
      const reason = "Macro body must be a string.";
      lastError.value = reason;
      const result = failureFromLegacy(reason, `write:${kind}:${name}`);
      reportCommandFailure(`save macro ${kind}:${name}`, result);
      return result;
    }
    isBusy.value = true;
    const result = await macrosFacade.write(name, safeBody, kind);
    if (result.failed) {
      lastError.value = describeError(result.failureReason);
      reportCommandFailure(`save macro ${kind}:${name}`, result);
    } else {
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
    }
    isBusy.value = false;
    return result;
  }

  /**
   * Remove a macro from disk and drop its cached content. The
   * matching per-kind listing is patched in place; the other two
   * listings stay warm.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   * @returns {Promise<CommandResult>}
   */
  async function deleteMacro(kind, name): Promise<CommandResult> {
    validateMacroKindName(kind, name);
    isBusy.value = true;
    const result = await macrosFacade.remove(name, kind);
    if (result.failed) {
      lastError.value = describeError(result.failureReason);
      reportCommandFailure(`delete macro ${kind}:${name}`, result);
    } else {
      delete contents[cacheKey(kind, name)];
      useConsoleStore().success(`Deleted macro '${name}' (${kind}).`);
      const target = listRefFor(kind);
      const idx = target.value.findIndex((entry) => entry.name === name);
      if (idx !== -1) target.value.splice(idx, 1);
    }
    isBusy.value = false;
    return result;
  }

  // --- execute ------------------------------------------------- //

  /**
   * "Run" a ``macro`` row. Routes the call through
   * ``runMacroOfKind`` so the macro + ngc dispatch lives in one
   * place.
   *
   * @param {string} name
   * @returns {Promise<CommandResult>}
   */
  async function runMacro(name): Promise<CommandResult> {
    return runMacroOfKind(MACRO_KIND.MACRO, name);
  }

  /**
   * Single-dispatch runner. Both ``.macro`` and ``.ngc`` route through
   * the same backend endpoint:
   *
   *   * ``POST /api/v1/modules/macros/{name}/start?kind=macro`` —
   *     the backend reads the file, parses it into static / python
   *     blocks, and dispatches each static line into MDI via
   *     ``execute_gcode``. ``{python}`` blocks are skipped with a
   *     console-log warning.
   *   * ``POST /api/v1/modules/macros/{name}/start?kind=ngc`` —
   *     the backend issues a single ``o<{name}> call`` MDI command
   *     so the controller switches to MDI mode and runs the NGC
   *     subroutine.
   *   * ``.mcode`` is rejected by the endpoint with a 400 — the
   *     operator wraps an M-code call in a ``.macro`` instead.
   *
   * E-Stop is guarded up front so the operator sees a friendly
   * console error before the backend has to send one. The
   * backend additionally guards against an E-Stop flipping
   * mid-dispatch.
   *
   * The success branch carries the historical counter shape
   * ``{staticDispatched: number, pythonSkipped: number}`` as a
   * JSON string on ``result.message`` so existing dashboard widgets
   * that read ``lastResult.value.staticDispatched`` keep their
   * input. New code should branch on ``result.failed``.
   *
   * @param {"macro"|"ngc"|"mcode"} kind
   * @param {string} name
   * @returns {Promise<CommandResult>}
   */
  async function runMacroOfKind(kind, name): Promise<CommandResult> {
    validateMacroKindName(kind, name);
    const consoleStore = useConsoleStore();

    const machine = useMachineStore();
    if (machine.isEstopActive) {
      const result = failureFromLegacy(
        "Cannot run macros while the machine is in E-Stop.",
        `start:${kind}:${name}`,
      );
      reportCommandFailure(`run macro ${kind}:${name}`, result);
      return result;
    }

    if (kind === MACRO_KIND.MCODE) {
      const result = failureFromLegacy(
        `Running ${kind} files from the UI is not supported — wrap the call in a .macro file instead.`,
        `start:${kind}:${name}`,
      );
      reportCommandFailure(`run macro ${kind}:${name}`, result);
      return result;
    }

    isBusy.value = true;
    consoleStore.info(
      `Dispatching ${kind} macro '${name}' via the backend start endpoint.`,
    );
    const result = await macrosFacade.start(name, kind);
    if (result.failed) {
      lastError.value = describeError(result.failureReason);
      reportCommandFailure(`run macro ${kind}:${name}`, result);
      isBusy.value = false;
      return result;
    }
    consoleStore.success(`Macro '${name}' (${kind}) dispatched.`);
    const success = CommandResult.success({
      commandId: `start:${kind}:${name}`,
      message: counterPayload(1, 0),
    });
    isBusy.value = false;
    return success;
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
