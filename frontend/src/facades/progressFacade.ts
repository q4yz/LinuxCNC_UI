// Progress / program facade. Single UI-facing API for
// program-progress reads + lifecycle writes (load / run / pause /
// resume / stop / unload).
//
// Reads come from the shared base-thread snapshot
// (baseThread.progress: ProgramProgress). Writes go to the
// generated OpenAPI client (ModulesProgramService).
//
// All write actions return a CommandResult so callers never
// have to try/catch — failures are routed through
// ``reportCommandFailure`` at the store layer.

import {
  ModulesProgramService,
  ProgramFilesService,
} from "../../generated/api";
import { ProgramFile } from "../entities/progress";
import { toProgramFileListing } from "../mappers/programfilesMapper";
import { CommandResult } from "../entities";
import { describeError, errorStatus } from "../core/error-format";


export class ProgressFacade {
  /**
   * Fetch and map the list of available G-code programs.
   * Returns an empty array on 404.
   */
  public async listProgramFiles(): Promise<ProgramFile[]> {
    try {
      const listing = await ProgramFilesService.listFiles();
      // Delegate to the robust mapper we just built
      return toProgramFileListing(listing);
    } catch (err: unknown) {
      if (errorStatus(err) === 404) return [];
      throw err;
    }
  }

  /**
   * Internal helper to wrap API promises in a typed CommandResult.
   * The response body is ``StatusResponse`` (shape ``{status, message,
   * ...}``) — we surface ``message`` so the store can echo operator-
   * facing confirmation ("Program aborted", "Resumed", …).
   */
  private async _commandResultFrom(
    promise: Promise<{ status?: string; message?: string } | void>,
    commandId: string,
  ): Promise<CommandResult> {
    try {
      const response = (await promise) as
        | { status?: string; message?: string }
        | undefined;
      return CommandResult.success({
        commandId,
        message: response?.message ?? response?.status ?? "ok",
      });
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId,
        statusCode: errorStatus(err),
      });
    }
  }

  public async loadProgram(filename: string): Promise<CommandResult> {
    return this._commandResultFrom(
      ModulesProgramService.loadProgram({ filename }),
      `load:${filename}`,
    );
  }

  public async runProgram(): Promise<CommandResult> {
    return this._commandResultFrom(
      ModulesProgramService.runProgram(),
      "run",
    );
  }

  public async pauseProgram(): Promise<CommandResult> {
    return this._commandResultFrom(
      ModulesProgramService.pauseProgram(),
      "pause",
    );
  }

  public async resumeProgram(): Promise<CommandResult> {
    return this._commandResultFrom(
      ModulesProgramService.resumeProgram(),
      "resume",
    );
  }

  public async stopProgram(): Promise<CommandResult> {
    return this._commandResultFrom(
      ModulesProgramService.stopProgram(),
      "stop",
    );
  }

  public async unloadProgram(): Promise<CommandResult> {
    return this._commandResultFrom(
      ModulesProgramService.unloadProgram(),
      "unload",
    );
  }
}

// Export a singleton instance for drop-in compatibility with existing code
export const progressFacade = new ProgressFacade();
export default progressFacade;
