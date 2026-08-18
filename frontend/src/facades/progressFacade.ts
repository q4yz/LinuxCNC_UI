// Progress / program facade. Single UI-facing API for
// program-progress reads + lifecycle writes (load / run / pause /
// resume / stop / unload).
//
// Reads come from the shared base-thread snapshot
// (baseThread.progress: ProgramProgress). Writes go to the
// generated OpenAPI client (ModulesProgramService).
//
// All write actions return a CommandResult so callers never
// have to try/catch.

import {
    ModulesProgramService,
    ProgramFilesService,
} from "../../generated/api";
import {ProgramFile} from "../entities/progress";
import {toProgramFileListing} from "../mappers/programfilesMapper";
import {CommandResult} from "../entities";
import describeError from "../core/error-format";


// Progress / program facade. Single UI-facing API for
// program-progress reads + lifecycle writes (load / run / pause /
// resume / stop / unload).
//
// Reads come from the shared base-thread snapshot
// (baseThread.progress: ProgramProgress). Writes go to the
// generated OpenAPI client (ModulesProgramService).
//
// All write actions return a CommandResult so callers never
// have to try/catch.


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
        } catch (err: any) {
            const status = err?.status ?? err?.response?.status;
            if (status === 404) return [];
            throw err;
        }
    }

    /**
     * Internal helper to wrap API promises in a safe CommandResult.
     */
    private async _commandResultFrom(
        promise: Promise<any>,
        commandId: string
    ): Promise<CommandResult> {
        try {
            await promise;
            return CommandResult.success({commandId});
        } catch (err: any) {
            return CommandResult.failure(describeError(err), {
                commandId,
                message: "Program command failed",
            });
        }
    }

    public async loadProgram(filename: string): Promise<CommandResult> {
        return this._commandResultFrom(
            ModulesProgramService.loadProgram({filename}),
            filename,
        );
    }

    public async runProgram(): Promise<CommandResult> {
        return this._commandResultFrom(ModulesProgramService.runProgram(), "run");
    }

    public async pauseProgram(): Promise<CommandResult> {
        return this._commandResultFrom(ModulesProgramService.pauseProgram(), "pause");
    }

    public async resumeProgram(): Promise<CommandResult> {
        return this._commandResultFrom(ModulesProgramService.resumeProgram(), "resume");
    }

    public async stopProgram(): Promise<CommandResult> {
        return this._commandResultFrom(ModulesProgramService.stopProgram(), "stop");
    }

    public async unloadProgram(): Promise<CommandResult> {
        return this._commandResultFrom(ModulesProgramService.unloadProgram(), "unload");
    }
}

// Export a singleton instance for drop-in compatibility with existing code
export const progressFacade = new ProgressFacade();
export default progressFacade;