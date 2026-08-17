// Macros facade. CRUD + parse. Wraps the generated ``ModulesMacrosService``
// and ``macros/parser.js``.

import { ModulesMacrosService } from "../../generated/api/index.ts";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError } from "../core/error-format";

async function _commandResultFrom(promise, commandId) {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId,
      message: "Macro command failed",
    });
  }
}

async function list(kind) {
  const listing = await ModulesMacrosService.listMacros({ kind });
  return listing;
}

async function read(name, kind) {
  return ModulesMacrosService.getMacroContent({ name, kind });
}

async function write(name, content, kind) {
  return _commandResultFrom(
    ModulesMacrosService.putMacroContent({ name, kind, content: { content } }),
    `write:${kind}:${name}`,
  );
}

async function remove(name, kind) {
  return _commandResultFrom(
    ModulesMacrosService.deleteMacro({ name, kind }),
    `delete:${kind}:${name}`,
  );
}

export const macrosFacade = Object.freeze({
  list,
  read,
  write,
  remove,
});

export default macrosFacade;
