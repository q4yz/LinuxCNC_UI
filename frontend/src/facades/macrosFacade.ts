// Macros facade. CRUD + parse. Wraps the generated ``ModulesMacrosService``.
// Every write / dispatch action returns a ``CommandResult`` so the
// store / component layer can route through ``reportCommandFailure``.
// Reads keep their raw return shape so the existing ``loadList`` /
// ``readMacro`` call sites don't have to be rewritten.

import { ModulesMacrosService } from "../../generated/api/index.ts";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

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

async function list(kind: string) {
  const listing = await ModulesMacrosService.listMacros(kind);
  return listing;
}

async function read(name: string, kind: string) {
  return ModulesMacrosService.readMacro(name, kind);
}

async function write(
  name: string,
  content: string,
  kind: string,
): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMacrosService.writeMacro(name, content, kind),
    `write:${kind}:${name}`,
  );
}

async function remove(
  name: string,
  kind: string,
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
  kind: string,
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
