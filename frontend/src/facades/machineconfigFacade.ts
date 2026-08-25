// Machineconfig facade. CRUD for profiles + compile / deploy
// pipeline. Wraps the generated ``ModulesMachineconfigService``.
// Every write returns a ``CommandResult`` so the store can route
// its failure log through ``reportCommandFailure``.

import { ModulesMachineconfigService } from "../../generated/api/index.ts";
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

async function listCompilers() {
  return ModulesMachineconfigService.listCompilersApiV1ModulesMachineconfigCompilersGet();
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

// --- Compile / deploy -------------------------------------------------

async function compileProfile({
  profile_path,
  compiler_id,
}: {
  profile_path: string;
  compiler_id: string;
}): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.compileProfileApiV1ModulesMachineconfigCompilePost({
      profile_path,
      compiler_id,
    }),
    `compile:${profile_path}:${compiler_id}`,
  );
}

async function deployStaged({
  confirm_flash = false,
}: { confirm_flash?: boolean } = {}): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineconfigService.deployStagedApiV1ModulesMachineconfigDeployPost({
      confirm_flash,
    }),
    "deploy",
  );
}

// --- Staged / active --------------------------------------------------

async function listStaged() {
  return ModulesMachineconfigService.listStagedApiV1ModulesMachineconfigStagedGet();
}

async function listActive() {
  return ModulesMachineconfigService.listActiveApiV1ModulesMachineconfigActiveGet();
}

async function readStagedContent(name: string) {
  return ModulesMachineconfigService.readStagedApiV1ModulesMachineconfigStagedContentNameGet(
    name,
  );
}

async function readActiveContent(name: string) {
  return ModulesMachineconfigService.readActiveApiV1ModulesMachineconfigActiveContentNameGet(
    name,
  );
}

export const machineconfigFacade = Object.freeze({
  listProfiles,
  listCompilers,
  readProfile,
  writeProfile,
  createFolder,
  createFile,
  uploadProfile,
  renameProfile,
  deleteProfile,
  compileProfile,
  deployStaged,
  listStaged,
  listActive,
  readStagedContent,
  readActiveContent,
});

export default machineconfigFacade;
