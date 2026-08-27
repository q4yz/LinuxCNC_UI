// Editor facade. UI-facing API for the universal editor's reads +
// writes. Dispatches by ``EditorSource`` so consumers never have
// to branch on which endpoint to call.

import {
  ProgramFilesService,
  ModulesMachineconfigService,
  ModulesMacrosService,
} from "../../generated/api/index";
import { ApiError } from "../../generated/api/core/ApiError";
import { CommandResult } from "../entities/common/CommandResult";
import {
  EditorDocument,
  type EditorSource,
} from "../entities/editor/EditorDocument";
import { describeError, errorStatus } from "../core/error-format";

async function readDocument(source: EditorSource, path: string): Promise<unknown> {
  switch (source) {
    case "profiles":
      return ModulesMachineconfigService.readProfileApiV1ModulesMachineconfigProfilesContentGet(path);
    case "active":
      return ModulesMachineconfigService.readActiveApiV1ModulesMachineconfigActiveContentNameGet(path);
    case "staged":
      return ModulesMachineconfigService.readStagedApiV1ModulesMachineconfigStagedContentNameGet(path);
    case "m_codes":
      return ModulesMachineconfigService.readMCode(path);
    case "programs":
      return ProgramFilesService.readFile(path);
    case "macros":
      return ModulesMacrosService.readMacroContent(path, "macro");
    default:
      throw new Error(`Unhandled source ${source as string}`);
  }
}

async function writeDocument(
  source: EditorSource,
  path: string,
  content: string,
): Promise<unknown> {
  switch (source) {
    case "profiles":
      return ModulesMachineconfigService.saveProfileApiV1ModulesMachineconfigProfilesContentPut(path, {
        content,
      });
    case "m_codes":
      return ModulesMachineconfigService.writeMCode(path, { content });
    case "programs":
      return ProgramFilesService.writeFile(path, { content });
    case "macros":
      return ModulesMacrosService.writeMacroContent(path, { content }, "macro");
    default:
      throw new Error(`Read-only source ${source as string}`);
  }
}

/**
 * Open a document. Returns an ``EditorDocument`` (or throws on
 * hard errors — the editor store catches and surfaces).
 */
async function open(source: EditorSource, path: string): Promise<EditorDocument> {
  const content = await readDocument(source, path);
  const text = typeof content === "string" ? content : "";
  return new EditorDocument({ source, path, content: text });
}

/**
 * Save a document. Returns a ``CommandResult``.
 */
async function save(doc: EditorDocument): Promise<CommandResult> {
  try {
    await writeDocument(doc.source as EditorSource, doc.path, doc.content);
    return CommandResult.success({ commandId: `${doc.source}:${doc.path}` });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId: `${doc.source}:${doc.path}`,
      statusCode: errorStatus(err),
    });
  }
}

export const editorFacade = Object.freeze({
  open,
  save,
});

export default editorFacade;
