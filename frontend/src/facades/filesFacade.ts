// Files facade. UI-facing API for program file CRUD. Wraps the
// generated ``ProgramFilesService`` + ``ActivePrintWidget``-facing
// helpers.

import {
  ProgramFilesService,
} from "../../generated/api/index.ts";
import { CommandResult } from "../entities/common/CommandResult";
import { FileEntry } from "../entities/files/FileEntry";
import { toFileListing } from "../mappers/filesMapper";
import { describeError, errorStatus } from "../core/error-format";

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

async function uploadFile(path: string, blob: Blob): Promise<CommandResult> {
  return _commandResultFrom(
    ProgramFilesService.uploadFile({ path, file: blob }),
    `upload:${path}`,
  );
}

async function deleteFile(path: string): Promise<CommandResult> {
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
