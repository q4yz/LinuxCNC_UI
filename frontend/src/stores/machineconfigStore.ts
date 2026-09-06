// Machineconfig module Pinia store. Owns the profiles tree and the
// machines tree (template generation). The backend is the source of
// truth — we re-fetch per action rather than caching, so operators
// always see current values after a refetch. See ``.agent/STATE.md``
// § 2.
//
// Two things this store used to own were removed from the backend
// and from the UI: the compiler / staged / confirm-flash deploy
// pipeline (`ProfilesExplorer` generates + `MachinesExplorer` edits
// templates instead), and the later ``active/`` copy step — a
// machine's config now lives directly under
// ``machine_config/machines/<name>/`` and is addressed by name (see
// ``MachineLifecycleService``). The corresponding store state/actions
// were deleted rather than patched to match a contract that no
// longer exists.
//
// All HTTP calls go through ``machineconfigFacade`` (which wraps
// the OpenAPI-generated ``ModulesMachineconfigService``). Reads
// keep their legacy return shapes; every manual-write action —
// saveProfile, createFolder, createFile, uploadProfiles,
// renameProfile, deleteProfile — returns ``Promise<CommandResult>``
// so the UI layer has a uniform response and failures channel
// through ``reportCommandFailure``.

import { defineStore } from "pinia";
import { computed, reactive, ref } from "vue";

import { useConsoleStore } from "./console";
import {
  describeError as describeErrorShared,
  errorStatus,
  reportCommandFailure,
} from "../core/error-format";
import { CommandResult } from "../entities/common/CommandResult";
import { machineconfigFacade } from "../facades/machineconfigFacade";
import type { DirectoryEntryModel } from "../../generated/api/models/DirectoryEntryModel";

const STORE_ID = "machineconfig";

interface ProfilesTree {
  root: string;
  entries: DirectoryEntryModel[];
}

export interface MachineGenerateOutcome {
  status: "ok" | "conflict" | "error";
  machine: string | null;
  existing: string[];
}

export const useMachineConfigStore = defineStore(STORE_ID, () => {
  const consoleStore = useConsoleStore();

  // --- Reactive state ---------------------------------------------- //

  const profilesTree = reactive<ProfilesTree>({ root: "profiles", entries: [] });
  const selectedProfilePath = ref<string>("");

  const machinesTree = reactive<ProfilesTree>({ root: "machines", entries: [] });

  const isBusy = ref<boolean>(false);

  // --- Derived state ----------------------------------------------- //

  const selectedProfile = computed<DirectoryEntryModel | null>(() => {
    const path = selectedProfilePath.value;
    if (!path) return null;
    return (
      profilesTree.entries.find(
        (e: DirectoryEntryModel) => e.path === path && e.kind === "file",
      ) || null
    );
  });

  // --- Error-mapping helper --------------------------------------- //
  //
  // The generated client throws ``ApiError`` on failure; plain
  // ``Error`` instances bubble through unchanged. The store wants
  // the same operator-readable message it used to get from the
  // legacy wrapper. Shared with ``stores/macrosStore.ts`` and
  // ``components/FileManager.vue`` via ``core/error-format.js`` so
  // a future envelope shape change lives in one place.
  const describeError = (error: unknown): string =>
    describeErrorShared(error) || "Unknown error";

  function commandResultFromCaught(
    error: unknown,
    commandId: string,
  ): CommandResult {
    return CommandResult.failure(describeError(error), {
      commandId,
      statusCode: errorStatus(error),
    });
  }

  // --- Loader actions --------------------------------------------- //
  //
  // Loader (read) actions keep the legacy void return shape — they
  // log their own errors via ``consoleStore.error`` because their
  // failure is informational (background refetch), not an operator
  // action.

  async function loadProfilesTree(): Promise<void> {
    try {
      const response = await machineconfigFacade.listProfiles();
      profilesTree.entries.splice(0, profilesTree.entries.length);
      for (const entry of (response as { entries?: DirectoryEntryModel[] }).entries || []) {
        profilesTree.entries.push(entry);
      }
    } catch (error: unknown) {
      const result = commandResultFromCaught(error, "load-profiles-tree");
      reportCommandFailure("load profiles tree", result);
    }
  }

  async function loadMachinesTree(): Promise<void> {
    try {
      const response = await machineconfigFacade.listMachines();
      machinesTree.entries.splice(0, machinesTree.entries.length);
      for (const entry of (response as { entries?: DirectoryEntryModel[] }).entries || []) {
        machinesTree.entries.push(entry);
      }
    } catch (error: unknown) {
      const result = commandResultFromCaught(error, "load-machines-tree");
      reportCommandFailure("load machines tree", result);
    }
  }

  async function loadAll(): Promise<void> {
    await Promise.all([
      loadProfilesTree(),
      loadMachinesTree(),
    ]);
  }

  // --- Profile actions -------------------------------------------- //

  function selectProfile(path: string): void {
    selectedProfilePath.value = path || "";
  }

  async function readProfileContent(path: string): Promise<string | null> {
    try {
      const response = await machineconfigFacade.readProfile(path);
      return response.content || "";
    } catch (error: unknown) {
      consoleStore.error(`Failed to read ${path}: ${describeError(error)}`);
      return null;
    }
  }

  async function saveProfile(path: string, content: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.writeProfile(path, content);
    if (result.failed) {
      reportCommandFailure(`save profile ${path}`, result);
    } else {
      consoleStore.success(`Saved ${path}`);
      await loadProfilesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function createFolder(path: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.createFolder(path);
    if (result.failed) {
      reportCommandFailure(`create folder ${path}`, result);
    } else {
      consoleStore.success(`Created folder ${path}`);
      await loadProfilesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function createFile(path: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.createFile(path);
    if (result.failed) {
      reportCommandFailure(`create file ${path}`, result);
    } else {
      consoleStore.success(`Created file ${path}`);
      await loadProfilesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function uploadProfiles(
    directory: string,
    files: File[],
  ): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.uploadProfile(directory, files);
    if (result.failed) {
      reportCommandFailure("upload profiles", result);
    } else {
      consoleStore.success(`Uploaded ${files.length} profile file(s)`);
      await loadProfilesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function renameProfile(
    source: string,
    destination: string,
  ): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.renameProfile(source, destination);
    if (result.failed) {
      reportCommandFailure(`rename ${source} -> ${destination}`, result);
    } else {
      consoleStore.success(`Renamed ${source} -> ${destination}`);
      if (selectedProfilePath.value === source) {
        selectedProfilePath.value = destination;
      }
      await loadProfilesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function deleteProfile(path: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.deleteProfile(path);
    if (result.failed) {
      reportCommandFailure(`delete profile ${path}`, result);
    } else {
      consoleStore.success(`Deleted ${path}`);
      if (selectedProfilePath.value === path) {
        selectedProfilePath.value = "";
      }
      await loadProfilesTree();
    }
    isBusy.value = false;
    return result;
  }

  // --- Machines (template generation + CRUD) ---------------------- //

  /**
   * Generate the machine template set from a profile. A structured
   * 409 (machine already exists) resolves as ``status: "conflict"``
   * WITHOUT toasting — the caller drives the "override?" confirm
   * modal and retries with ``confirmOverride: true``.
   */
  async function generateMachine(
    profilePath: string,
    opts: { targetFolder?: string; confirmOverride?: boolean } = {},
  ): Promise<MachineGenerateOutcome> {
    if (!profilePath) {
      return { status: "error", machine: null, existing: [] };
    }
    isBusy.value = true;
    const outcome = await machineconfigFacade.generateMachine({
      profile_path: profilePath,
      target_folder: opts.targetFolder ?? "",
      confirm_override: opts.confirmOverride ?? false,
    });
    isBusy.value = false;

    if (outcome.result.ok) {
      consoleStore.success(
        `Generated machine templates for ${outcome.machine ?? profilePath}.`,
      );
      await loadMachinesTree();
      return { status: "ok", machine: outcome.machine, existing: [] };
    }
    if (outcome.existsConflict) {
      return {
        status: "conflict",
        machine: outcome.existsConflict.machine,
        existing: outcome.existsConflict.existing,
      };
    }
    reportCommandFailure("generate machine", outcome.result);
    return { status: "error", machine: outcome.machine, existing: [] };
  }

  async function readMachineContent(path: string): Promise<string | null> {
    try {
      const response = await machineconfigFacade.readMachine(path);
      return response.content || "";
    } catch (error: unknown) {
      consoleStore.error(`Failed to read ${path}: ${describeError(error)}`);
      return null;
    }
  }

  async function saveMachine(path: string, content: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.writeMachine(path, content);
    if (result.failed) {
      reportCommandFailure(`save machine file ${path}`, result);
    } else {
      consoleStore.success(`Saved ${path}`);
      await loadMachinesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function createMachineFolder(path: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.createMachineFolder(path);
    if (result.failed) {
      reportCommandFailure(`create folder ${path}`, result);
    } else {
      consoleStore.success(`Created folder ${path}`);
      await loadMachinesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function createMachineFile(path: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.createMachineFile(path);
    if (result.failed) {
      reportCommandFailure(`create file ${path}`, result);
    } else {
      consoleStore.success(`Created file ${path}`);
      await loadMachinesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function uploadMachines(
    directory: string,
    files: File[],
  ): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.uploadMachine(directory, files);
    if (result.failed) {
      reportCommandFailure("upload machine files", result);
    } else {
      consoleStore.success(`Uploaded ${files.length} machine file(s)`);
      await loadMachinesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function renameMachine(
    source: string,
    destination: string,
  ): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.renameMachine(source, destination);
    if (result.failed) {
      reportCommandFailure(`rename ${source} -> ${destination}`, result);
    } else {
      consoleStore.success(`Renamed ${source} -> ${destination}`);
      await loadMachinesTree();
    }
    isBusy.value = false;
    return result;
  }

  async function deleteMachine(path: string): Promise<CommandResult> {
    isBusy.value = true;
    const result = await machineconfigFacade.deleteMachine(path);
    if (result.failed) {
      reportCommandFailure(`delete machine entry ${path}`, result);
    } else {
      consoleStore.success(`Deleted ${path}`);
      await loadMachinesTree();
    }
    isBusy.value = false;
    return result;
  }

  // --- Public surface --------------------------------------------- //

  return {
    profilesTree,
    selectedProfilePath,
    selectedProfile,
    machinesTree,
    isBusy,
    loadProfilesTree,
    loadMachinesTree,
    loadAll,
    selectProfile,
    readProfileContent,
    saveProfile,
    createFolder,
    createFile,
    uploadProfiles,
    renameProfile,
    deleteProfile,
    generateMachine,
    readMachineContent,
    saveMachine,
    createMachineFolder,
    createMachineFile,
    uploadMachines,
    renameMachine,
    deleteMachine,
  };
});
