// Macros facade. CRUD + parse. Wraps the generated ``ModulesMacrosService``.
// Every write / dispatch action returns a ``CommandResult`` so the
// store / component layer can route through ``reportCommandFailure``.
// Reads keep their raw return shape so the existing ``loadList`` /
// ``readMacro`` call sites don't have to be rewritten.

import { ModulesMacrosService } from "../../generated/api/index";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";
import type { MacroListResponse } from "../../generated/api/models/MacroListResponse";
import type { MacroKind } from "../stores/macrosTypes";

async function _commandResultFrom(
  promise: Promise<unknown>,
  commandId: string,
): Promise<CommandResult> {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId,
      statusCode: errorStatus(err),
    });
  }
}

async function list(kind: MacroKind): Promise<MacroListResponse> {
  return ModulesMacrosService.listMacros(kind);
}

/**
 * Unwrap the generated client's loose ``any`` response from
 * ``readMacro``. The wire returns the macro body as ``text/plain``,
 * which the codegen types as ``any``; we narrow to ``string``.
 */
function unwrapReadResponse(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  return String(value);
}

async function read(name: string, kind: MacroKind): Promise<string> {
  return unwrapReadResponse(await ModulesMacrosService.readMacro(name, kind));
}

async function write(
  name: string,
  content: string,
  kind: MacroKind,
): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMacrosService.writeMacro(name, content, kind),
    `write:${kind}:${name}`,
  );
}

async function remove(
  name: string,
  kind: MacroKind,
): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMacrosService.deleteMacro(name, kind),
    `delete:${kind}:${name}`,
  );
}

/**
 * Dispatch the macro via the unified ``startMacro`` endpoint
 * (``POST /api/v1/modules/macros/{name}/start?kind=macro|ngc``).
 * ``.mcode`` is rejected by the endpoint with 400 — the store
 * surfaces that via ``reportCommandFailure``.
 */
async function start(
  name: string,
  kind: MacroKind,
): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMacrosService.startMacro(name, kind),
    `start:${kind}:${name}`,
  );
}

export const macrosFacade = Object.freeze({
  list,
  read,
  write,
  remove,
  start,
});

export default macrosFacade;