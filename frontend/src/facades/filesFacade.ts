// Files facade. UI-facing API for program file CRUD. Wraps the
// generated ``ProgramFilesService`` + ``ActivePrintWidget``-facing
// helpers.

import {
  ProgramFilesService,
} from "../../generated/api/index";
import { CommandResult } from "../entities/common/CommandResult";
import { FileEntry } from "../entities/files/FileEntry";
import { toFileListing } from "../mappers/filesMapper";
import { describeError, errorStatus } from "../core/error-format";

/**
 * @returns {Promise<FileEntry[]>}
 */
async function listFiles(): Promise<ReturnType<typeof toFileListing>> {
  try {
    const wire = await ProgramFilesService.listFiles();
    return toFileListing(Array.isArray(wire) ? wire : []);
  } catch (err: unknown) {
    if (err && typeof err === "object") {
      const status = (err as { status?: unknown }).status;
      if (status === 404) return [];
    }
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
  // ``ProgramFilesService.uploadFile`` accepts a single
  // ``Body_uploadFile`` envelope (just ``file`` — ``path`` is
  // encoded in the multipart form by the caller). The generated
  // type declares ``file`` as ``string`` but multipart upload
  // accepts ``File`` / ``Blob`` at runtime, so pass the raw value
  // through.
  return _commandResultFrom(
    ProgramFilesService.uploadFile({ file: blob as unknown as string }),
    `upload:${path}`,
  );
}

async function deleteFile(path: string): Promise<CommandResult> {
  return _commandResultFrom(
    ProgramFilesService.deleteFile(path),
    `delete:${path}`,
  );
}

export const filesFacade = Object.freeze({
  listFiles,
  uploadFile,
  deleteFile,
});

export default filesFacade;
