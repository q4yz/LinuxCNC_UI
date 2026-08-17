// Editor facade. UI-facing API for the universal editor's reads +
// writes. Dispatches by ``EditorSource`` so consumers never have
// to branch on which endpoint to call.

import {
  ProgramFilesService,
  ModulesMachineconfigService,
  ModulesMacrosService,
} from "../../generated/api/index.ts";
import { ApiError } from "../../generated/api/core/ApiError";
import { CommandResult } from "../entities/common/CommandResult.js";
import {
  EditorSource,
  EditorDocument,
  isEditorSource,
} from "../entities/editor/EditorDocument.js";
import { describeError } from "../core/error-format.js";

async function readDocument(source, path) {
  if (!isEditorSource(source)) {
    throw new Error(`Unknown source ${source}`);
  }
  switch (source) {
    case EditorSource.PROFILES:
      return ModulesMachineconfigService.getMachineconfigProfilesContent({ path });
    case EditorSource.ACTIVE:
      return ModulesMachineconfigService.getMachineconfigActiveContent({ name: path });
    case EditorSource.STAGED:
      return ModulesMachineconfigService.getMachineconfigStagedContent({ name: path });
    case EditorSource.M_CODES:
      return ModulesMachineconfigService.getMachineconfigMCodesContent({ path });
    case EditorSource.PROGRAMS:
      return ProgramFilesService.getContentPrograms({ filename: path });
    case EditorSource.MACROS:
      return ModulesMacrosService.getMacroContent({ name: path });
    default:
      throw new Error(`Unhandled source ${source}`);
  }
}

async function writeDocument(source, path, content) {
  if (!isEditorSource(source)) {
    throw new Error(`Unknown source ${source}`);
  }
  switch (source) {
    case EditorSource.PROFILES:
      return ModulesMachineconfigService.putMachineconfigProfilesContent({
        path,
        content: { content },
      });
    case EditorSource.M_CODES:
      return ModulesMachineconfigService.putMachineconfigMCodesContent({
        path,
        content: { content },
      });
    case EditorSource.PROGRAMS:
      return ProgramFilesService.putContentPrograms({ filename: path, content });
    case EditorSource.MACROS:
      return ModulesMacrosService.putMacroContent({
        name: path,
        content: { content },
      });
    default:
      throw new Error(`Read-only source ${source}`);
  }
}

/**
 * Open a document. Returns an ``EditorDocument`` (or throws on
 * hard errors — the editor store catches and surfaces).
 */
async function open(source, path) {
  const content = await readDocument(source, path);
  const text = typeof content === "string" ? content : "";
  return new EditorDocument({ source, path, content: text });
}

/**
 * Save a document. Returns a ``CommandResult``.
 */
async function save(doc) {
  try {
    await writeDocument(doc.source, doc.path, doc.content);
    return CommandResult.success({ commandId: `${doc.source}:${doc.path}` });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId: `${doc.source}:${doc.path}`,
      message: "Save failed",
    });
  }
}

export const editorFacade = Object.freeze({
  open,
  save,
});

export default editorFacade;
