// Files facade. UI-facing API for program file CRUD. Wraps the
// generated ``ProgramFilesService`` + ``ActivePrintWidget``-facing
// helpers.

import {
  ProgramFilesService,
} from "../../generated/api/index.ts";
import { CommandResult } from "../entities/common/CommandResult";
import { FileEntry } from "../entities/files/FileEntry";
import { toFileListing } from "../mappers/filesMapper";
import { describeError } from "../core/error-format";

/**
 * @returns {Promise<FileEntry[]>}
 */
async function listFiles() {
  try {
    const wire = await ProgramFilesService.listFiles();
    return toFileListing(Array.isArray(wire) ? wire : []);
  } catch (err) {
    const status = err && (err.status ?? err.response?.status);
    if (status === 404) return [];
    throw err;
  }
}

async function _commandResultFrom(promise, commandId) {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId,
      message: "File command failed",
    });
  }
}

async function uploadFile(path, blob) {
  return _commandResultFrom(
    ProgramFilesService.uploadFile({ path, file: blob }),
    `upload:${path}`,
  );
}

async function deleteFile(path) {
  return _commandResultFrom(
    ProgramFilesService.deleteFile({ path }),
    `delete:${path}`,
  );
}

export const filesFacade = Object.freeze({
  listFiles,
  uploadFile,
  deleteFile,
});

export default filesFacade;
