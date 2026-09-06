// Machineconfig facade. CRUD for profiles + machines (template
// generation). Wraps the generated ``ModulesMachineconfigService``.
// Every write returns a ``CommandResult`` so the store can route its
// failure log through ``reportCommandFailure``.
//
// Two things this facade used to wrap no longer exist on the
// backend: the compile / staged / confirm-flash deploy pipeline, and
// the later ``active/`` copy step (``GET /active`` + content,
// ``POST /deploy``) — a machine's config now lives directly under
// ``machine_config/machines/<name>/`` and is addressed by name
// (see ``MachineLifecycleService``). The corresponding wrapper
// functions were deleted rather than patched to call endpoints that
// no longer exist.

import { ModulesMachineconfigService, ApiError } from "../../generated/api/index";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

async function _commandResultFrom(
  promise: Promise<{ status?: string; message?: string } | void>,
  commandId: string,
): Promise<CommandResult> {
  try {
    const response = (await promise) as
      | { status?: string; message?: string }
      | undefined;
    return CommandResult.success({
      commandId,
      message: response?.status ?? "ok",
    });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId,
      statusCode: errorStatus(err),
    });
  }
}

// --- Profiles CRUD ----------------------------------------------------

async function listProfiles() {
  return ModulesMachineconfigService.getProfilesTreeApiV1ModulesMachineconfigProfilesTreeGet();
}

async function readProfile(path: string) {
  return ModulesMachineconfigService.readProfileApiV1ModulesMachineconfigProfilesContentGet(
    path,
  );
}

async function writeProfile(
  path: string,
  content: string,
): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.saveProfileApiV1ModulesMachineconfigProfilesContentPut(
      path,
      { content },
    ),
    `profile:${path}`,
  );
}

async function createFolder(path: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.createFolderApiV1ModulesMachineconfigProfilesFolderPost({
      path,
    }),
    `folder:${path}`,
  );
}

async function createFile(path: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.createFileApiV1ModulesMachineconfigProfilesFilePost({
      path,
    }),
    `file:${path}`,
  );
}

async function uploadProfile(
  directory: string,
  files: File[],
): Promise<CommandResult> {
  // Upload is sequence-sensitive: a failure on file N must abort the
  // remaining uploads. Surface only a single ``CommandResult`` so
  // the store can react uniformly.
  try {
    for (const file of files) {
      const path = [directory, file.name].filter(Boolean).join("/");
      // ``Body_upload_profile...post.file`` is typed as ``string``
      // by the codegen but ``request.ts::isBlob`` accepts ``File``
      // at runtime. Pass the raw ``File`` so multipart upload works.
      await ModulesMachineconfigService.uploadProfileApiV1ModulesMachineconfigProfilesUploadPost(
        path,
        { file: file as unknown as string },
      );
    }
    return CommandResult.success({
      commandId: `upload:${directory}`,
      message: `Uploaded ${files.length} file(s)`,
    });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId: `upload:${directory}`,
      statusCode: errorStatus(err),
    });
  }
}

async function renameProfile(
  source: string,
  destination: string,
): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.renameProfileApiV1ModulesMachineconfigProfilesRenamePut({
      source,
      destination,
    }),
    `rename:${source}->${destination}`,
  );
}

async function deleteProfile(path: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.deleteProfileApiV1ModulesMachineconfigProfilesEntryDelete(
      path,
    ),
    `delete-profile:${path}`,
  );
}

// --- Machines (template generation + CRUD) -----------------------------

export interface GenerateMachineParams {
  profile_path: string;
  target_folder?: string;
  confirm_override?: boolean;
}

export interface MachineExistsConflict {
  machine: string;
  existing: string[];
}

export interface GenerateMachineOutcome {
  result: CommandResult;
  /** Machine name on success (``null`` on failure). */
  machine: string | null;
  /** Structured 409 payload when the machine already exists. */
  existsConflict: MachineExistsConflict | null;
}

/**
 * Generate the per-machine template set. Unlike the generic command
 * helpers this surfaces the structured 409 (machine already exists)
 * so the store / component can drive the "override?" confirm modal
 * instead of toasting an error.
 */
async function generateMachine({
  profile_path,
  target_folder = "",
  confirm_override = false,
}: GenerateMachineParams): Promise<GenerateMachineOutcome> {
  try {
    const response = await ModulesMachineconfigService.generateMachineApiV1ModulesMachineconfigMachinesGeneratePost({
      profile_path,
      target_folder: target_folder || undefined,
      confirm_override,
    });
    return {
      result: CommandResult.success({
        commandId: `generate:${profile_path}`,
        message: response?.status ?? "ok",
      }),
      machine: response?.machine ?? null,
      existsConflict: null,
    };
  } catch (err: unknown) {
    if (err instanceof ApiError && err.status === 409) {
      const detail = (err.body as { detail?: { kind?: string; machine?: string; existing?: string[] } } | undefined)
        ?.detail;
      if (detail?.kind === "machine_exists") {
        return {
          result: CommandResult.failure(describeError(err), {
            commandId: `generate:${profile_path}`,
            statusCode: err.status,
          }),
          machine: detail.machine ?? null,
          existsConflict: {
            machine: detail.machine ?? "",
            existing: detail.existing ?? [],
          },
        };
      }
    }
    return {
      result: CommandResult.failure(describeError(err), {
        commandId: `generate:${profile_path}`,
        statusCode: errorStatus(err),
      }),
      machine: null,
      existsConflict: null,
    };
  }
}

async function listMachines() {
  return ModulesMachineconfigService.getMachinesTreeApiV1ModulesMachineconfigMachinesTreeGet();
}

async function readMachine(path: string) {
  return ModulesMachineconfigService.readMachineFileApiV1ModulesMachineconfigMachinesContentGet(path);
}

async function writeMachine(path: string, content: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.saveMachineFileApiV1ModulesMachineconfigMachinesContentPut(
      path,
      { content },
    ),
    `machine:${path}`,
  );
}

async function createMachineFolder(path: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.createMachineFolderApiV1ModulesMachineconfigMachinesFolderPost({
      path,
    }),
    `machine-folder:${path}`,
  );
}

async function createMachineFile(path: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.createMachineFileApiV1ModulesMachineconfigMachinesFilePost({
      path,
    }),
    `machine-file:${path}`,
  );
}

async function uploadMachine(
  directory: string,
  files: File[],
): Promise<CommandResult> {
  try {
    for (const file of files) {
      const path = [directory, file.name].filter(Boolean).join("/");
      await ModulesMachineconfigService.uploadMachineFileApiV1ModulesMachineconfigMachinesUploadPost(
        path,
        { file: file as unknown as string },
      );
    }
    return CommandResult.success({
      commandId: `machine-upload:${directory}`,
      message: `Uploaded ${files.length} file(s)`,
    });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId: `machine-upload:${directory}`,
      statusCode: errorStatus(err),
    });
  }
}

async function renameMachine(source: string, destination: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.renameMachineEntryApiV1ModulesMachineconfigMachinesRenamePut({
      source,
      destination,
    }),
    `machine-rename:${source}->${destination}`,
  );
}

async function deleteMachine(path: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.deleteMachineEntryApiV1ModulesMachineconfigMachinesEntryDelete(
      path,
    ),
    `delete-machine:${path}`,
  );
}

export const machineconfigFacade = Object.freeze({
  listProfiles,
  readProfile,
  writeProfile,
  createFolder,
  createFile,
  uploadProfile,
  renameProfile,
  deleteProfile,
  generateMachine,
  listMachines,
  readMachine,
  writeMachine,
  createMachineFolder,
  createMachineFile,
  uploadMachine,
  renameMachine,
  deleteMachine,
});

export default machineconfigFacade;
