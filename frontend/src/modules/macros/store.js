// Macros module Pinia store. Fronts ``ModulesMacrosService`` (the
// OpenAPI-generated client) with state + cached payload + convenience
// actions. The "Run" action parses a macro into blocks and dispatches
// every ``static`` block via the machine module's MDI endpoint; the
// "execute python block" path is intentionally left as a console
// warning because the backend interpreter is not implemented yet.
//
// All HTTP calls go through the generated client so we keep types in
// sync with the OpenAPI schema. Errors are routed to ``useConsoleStore``,
// which the operator sees in the dashboard's persistent log.
//
// ``useConsoleStore`` is instantiated lazily inside each action to
// dodge the cross-store import cycle described in
// ``.agent/LESSONS_LEARNED.md`` § 2.4.

import { defineStore } from "pinia";
import { reactive, ref } from "vue";

import {
  ModulesMachineService,
  ModulesMacrosService,
} from "../../../generated/api/index.ts";
import manifest from "./manifest.js";
import { useConsoleStore } from "../../stores/console.js";
import { useMachineStore } from "../../stores/machine-compat.js";
import { parseMacro, validateMacroName } from "./parser.js";

const STORE_ID = `module_${manifest.id}`;

/**
 * Convert an arbitrary thrown value into a single operator-readable
 * sentence. Mirrors the shape used by the ``machineconfig`` store
 * so both surfaces surface errors the same way.
 *
 * @param {unknown} error
 * @returns {string}
 */
function describeError(error) {
  if (!error) return "Unknown error";
  if (typeof error === "object" && "body" in error && error.body) {
    const body = error.body;
    if (typeof body === "string") return body;
    if (typeof body === "object") {
      if (typeof body.detail === "string") return body.detail;
      if (Array.isArray(body.detail)) {
        return body.detail
          .map((entry) => entry?.msg || JSON.stringify(entry))
          .join("; ");
      }
    }
  }
  if (error instanceof Error) return error.message;
  return String(error);
}

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

export const useMacrosStore = defineStore(STORE_ID, () => {
  // --- reactive state ------------------------------------------ //

  /** Sorted list of macro names (no ``.macro`` suffix). */
  const macros = ref([]);

  /**
   * Cache of fetched payloads. Keyed by macro name. The dashboard
   * "Run" path populates this on first click so subsequent runs
   * skip the round-trip; the management panel populates it on
   * "Edit"; ``saveMacro`` keeps it in sync so the editor modal
   * does not show stale content.
   */
  const contents = reactive({});

  /** UI flag — true while a list mutation / delete / rename is in flight. */
  const isBusy = ref(false);

  /** Last error surfaced by an action (or ``null``). */
  const lastError = ref(/** @type {string|null} */ (null));

  // --- list / read / write / delete ---------------------------- //

  async function loadList() {
    try {
      const response = await ModulesMacrosService.listMacros();
      macros.value = Array.isArray(response?.macros) ? response.macros : [];
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(`Failed to list macros: ${lastError.value}`);
    }
  }

  /**
   * Fetch a macro's raw payload, cache it, and return the string.
   *
   * @param {string} name
   * @returns {Promise<string|null>} ``null`` when the fetch failed.
   */
  async function readMacro(name) {
    validateMacroName(name);
    try {
      const text = await ModulesMacrosService.readMacro(name);
      const payload = typeof text === "string" ? text : (text == null ? "" : String(text));
      contents[name] = payload;
      return payload;
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(`Failed to read macro '${name}': ${lastError.value}`);
      return null;
    }
  }

  /**
   * Cached lookup; falls back to a network fetch on miss.
   *
   * @param {string} name
   * @returns {Promise<string|null>}
   */
  async function ensureMacroContent(name) {
    if (typeof contents[name] === "string") return contents[name];
    return readMacro(name);
  }

  /**
   * Persist ``body`` under ``name`` (creating or overwriting).
   * Refreshes the list so a new name appears immediately.
   *
   * @param {string} name
   * @param {string} body
   * @returns {Promise<boolean>} Success flag.
   */
  async function saveMacro(name, body) {
    validateMacroName(name);
    if (typeof body !== "string") {
      lastError.value = "Macro body must be a string.";
      useConsoleStore().error(lastError.value);
      return false;
    }
    isBusy.value = true;
    try {
      await ModulesMacrosService.writeMacro(name, body);
      contents[name] = body;
      await loadList();
      useConsoleStore().success(`Saved macro '${name}' (${body.length} bytes).`);
      return true;
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(`Failed to save macro '${name}': ${lastError.value}`);
      return false;
    } finally {
      isBusy.value = false;
    }
  }

  /**
   * Convenience for "create new". The management UI uses ``saveMacro``
   * for both create and overwrite; the named alias reads better at
   * the call site.
   *
   * @param {string} name
   * @param {string} body
   */
  async function createMacro(name, body) {
    return saveMacro(name, body);
  }

  /**
   * Remove a macro from disk and drop its cached content.
   *
   * @param {string} name
   * @returns {Promise<boolean>}
   */
  async function deleteMacro(name) {
    validateMacroName(name);
    isBusy.value = true;
    try {
      await ModulesMacrosService.deleteMacro(name);
      delete contents[name];
      await loadList();
      useConsoleStore().success(`Deleted macro '${name}'.`);
      return true;
    } catch (error) {
      lastError.value = describeError(error);
      useConsoleStore().error(`Failed to delete macro '${name}': ${lastError.value}`);
      return false;
    } finally {
      isBusy.value = false;
    }
  }

  // --- execute ------------------------------------------------- //

  /**
   * "Run" a macro. Reads its content, parses it, and dispatches
   * each ``static`` block as one MDI command per non-blank line via
   * ``ModulesMachineService.runMdiCommand``. ``python`` blocks are
   * surfaced to the console as warnings — the backend interpreter is
   * not implemented yet, so we explicitly do not feed them to the
   * hardware layer.
   *
   * Guarded by ``isEstopActive`` so an E-Stop block aborts the run
   * before any MDI is dispatched.
   *
   * @param {string} name
   * @returns {Promise<{staticDispatched: number, pythonSkipped: number}>}
   */
  async function runMacro(name) {
    validateMacroName(name);
    const consoleStore = useConsoleStore();

    const machine = useMachineStore();
    if (machine.isEstopActive) {
      consoleStore.error("Cannot run macros while the machine is in E-Stop.");
      return { staticDispatched: 0, pythonSkipped: 0 };
    }

    const body = await ensureMacroContent(name);
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
    macros,
    contents,
    isBusy,
    lastError,
    loadList,
    readMacro,
    ensureMacroContent,
    saveMacro,
    createMacro,
    deleteMacro,
    runMacro,
  };
});

export default useMacrosStore;
