// Machineconfig facade. CRUD for profiles + compile / deploy
// pipeline. Wraps the generated ``ModulesMachineconfigService``.

import { ModulesMachineconfigService } from "../../generated/api/index.ts";
import { CommandResult } from "../entities/common/CommandResult.js";
import { describeError } from "../core/error-format.js";

async function _commandResultFrom(promise, commandId) {
  try {
    const response = await promise;
    return CommandResult.success({
      commandId,
      message: response && response.status ? response.status : "ok",
    });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId,
      message: "Machineconfig command failed",
    });
  }
}

// --- Profiles CRUD ----------------------------------------------------

async function listProfiles() {
  return ModulesMachineconfigService.getMachineconfigProfilesTree();
}

async function readProfile(path) {
  return ModulesMachineconfigService.getMachineconfigProfilesContent({ path });
}

async function writeProfile(path, content) {
  return _commandResultFrom(
    ModulesMachineconfigService.putMachineconfigProfilesContent({
      path,
      content: { content },
    }),
    `profile:${path}`,
  );
}

// --- Compile / deploy -------------------------------------------------

async function compileProfile({ profile_path, compiler_id }) {
  return _commandResultFrom(
    ModulesMachineconfigService.postMachineconfigCompile({
      profile_path,
      compiler_id,
    }),
    `compile:${profile_path}:${compiler_id}`,
  );
}

async function deployStaged({ confirm_flash = false } = {}) {
  return _commandResultFrom(
    ModulesMachineconfigService.postMachineconfigDeploy({ confirm_flash }),
    "deploy",
  );
}

// --- Staged / active --------------------------------------------------

async function listStaged() {
  return ModulesMachineconfigService.getMachineconfigStaged();
}

async function listActive() {
  return ModulesMachineconfigService.getMachineconfigActive();
}

async function readStagedContent(name) {
  return ModulesMachineconfigService.getMachineconfigStagedContent({ name });
}

async function readActiveContent(name) {
  return ModulesMachineconfigService.getMachineconfigActiveContent({ name });
}

export const machineconfigFacade = Object.freeze({
  listProfiles,
  readProfile,
  writeProfile,
  compileProfile,
  deployStaged,
  listStaged,
  listActive,
  readStagedContent,
  readActiveContent,
});

export default machineconfigFacade;
