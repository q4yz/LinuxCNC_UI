// Progress / program facade. Single UI-facing API for
// program-progress reads + lifecycle writes (load / run / pause /
// resume / stop / unload).
//
// Reads come from the shared base-thread snapshot
// (``baseThread.progress: ProgramProgress``). Writes go to the
// generated OpenAPI client (``ModulesProgramService``).
//
// All write actions return a ``CommandResult`` so callers never
// have to try/catch.

import {
  ModulesProgramService,
  ProgramFilesService,
} from "../../generated/api/index.ts";
import { CommandResult } from "../entities/common/CommandResult.js";
import { ProgramFile } from "../entities/progress/ProgramFile.js";
import { describeError } from "../core/error-format.js";

/**
 * @returns {Promise<ProgramFile[]>}
 */
async function listProgramFiles() {
  try {
    const listing = await ProgramFilesService.listFiles();
    if (!Array.isArray(listing)) return [];
    return listing
      .filter((entry) => entry && typeof entry === "object")
      .map(
        (entry) =>
          new ProgramFile({
            name: typeof entry.name === "string" ? entry.name : "",
            path: typeof entry.path === "string" ? entry.path : "",
            sizeBytes: Number(entry.size_bytes) || 0,
            kind: typeof entry.kind === "string" ? entry.kind : "file",
            modified: typeof entry.modified === "string" ? entry.modified : null,
          }),
      )
      .filter((file) => file.name.length > 0);
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
      message: "Program command failed",
    });
  }
}

async function loadProgram(filename) {
  return _commandResultFrom(
    ModulesProgramService.loadProgram({ filename }),
    filename,
  );
}

async function runProgram() {
  return _commandResultFrom(ModulesProgramService.runProgram(), "run");
}

async function pauseProgram() {
  return _commandResultFrom(ModulesProgramService.pauseProgram(), "pause");
}

async function resumeProgram() {
  return _commandResultFrom(ModulesProgramService.resumeProgram(), "resume");
}

async function stopProgram() {
  return _commandResultFrom(ModulesProgramService.stopProgram(), "stop");
}

async function unloadProgram() {
  return _commandResultFrom(ModulesProgramService.unloadProgram(), "unload");
}

export const progressFacade = Object.freeze({
  listProgramFiles,
  loadProgram,
  runProgram,
  pauseProgram,
  resumeProgram,
  stopProgram,
  unloadProgram,
});

export default progressFacade;
