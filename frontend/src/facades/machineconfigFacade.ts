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
import type { FileEntry } from "../entities/files";
import { toFileListing } from "../mappers/filesMapper";

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

/** Every file/folder under ``profiles/`` (flat, ``parent`` links them). */
async function listProfiles(): Promise<FileEntry[]> {
  const listing = await ModulesMachineconfigService.getProfilesTreeApiV1ModulesMachineconfigProfilesTreeGet();
  return toFileListing(listing?.entries);
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

/**
 * Upload several files into ``directory``, one request each. A failed
 * file does not stop the rest; the result names every file that
 * failed (and why), or reports how many were uploaded.
 */
async function _uploadEach(
  directory: string,
  files: File[],
  uploadOne: (path: string, file: File) => Promise<unknown>,
): Promise<CommandResult> {
  const commandId = `upload:${directory}`;
  const failures: string[] = [];
  let lastStatus: number | null = null;
  for (const file of files) {
    const path = [directory, file.name].filter(Boolean).join("/");
    try {
      await uploadOne(path, file);
    } catch (err: unknown) {
      failures.push(`${file.name}: ${describeError(err)}`);
      lastStatus = errorStatus(err);
    }
  }
  if (failures.length) {
    return CommandResult.failure(
      `${failures.length} of ${files.length} file(s) failed — ${failures.join("; ")}`,
      { commandId, statusCode: lastStatus },
    );
  }
  return CommandResult.success({ commandId, message: `Uploaded ${files.length} file(s)` });
}

async function uploadProfile(directory: string, files: File[]): Promise<CommandResult> {
  // ``Body_upload_profile...post.file`` is typed as ``string`` by the
  // codegen but ``request.ts::isBlob`` accepts ``File`` at runtime.
  return _uploadEach(directory, files, (path, file) =>
    ModulesMachineconfigService.uploadProfileApiV1ModulesMachineconfigProfilesUploadPost(
      path,
      { file: file as unknown as string },
    ),
  );
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

/** Every file/folder under ``machines/`` (flat, ``parent`` links them). */
async function listMachines(): Promise<FileEntry[]> {
  const listing = await ModulesMachineconfigService.getMachinesTreeApiV1ModulesMachineconfigMachinesTreeGet();
  return toFileListing(listing?.entries);
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

async function uploadMachine(directory: string, files: File[]): Promise<CommandResult> {
  return _uploadEach(directory, files, (path, file) =>
    ModulesMachineconfigService.uploadMachineFileApiV1ModulesMachineconfigMachinesUploadPost(
      path,
      { file: file as unknown as string },
    ),
  );
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
