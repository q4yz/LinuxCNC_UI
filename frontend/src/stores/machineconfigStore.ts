// Machineconfig module Pinia store. Owns the profiles tree, the
// compilers, the staged / active listings, the selected compiler,
// and the deployment toggles. The backend is the source of truth —
// we re-fetch per action rather than caching, so operators always
// see current values after a refetch. See ``.agent/STATE.md`` § 2.
//
// All HTTP calls go through ``machineconfigFacade`` (which wraps
// the OpenAPI-generated ``ModulesMachineconfigService``). Reads
// keep their legacy return shapes; every manual-write action —
// saveProfile, createFolder, createFile, uploadProfiles,
// renameProfile, deleteProfile, compile, deploy — returns
// ``Promise<CommandResult>`` so the UI layer has a uniform response
// and failures channel through ``reportCommandFailure``.

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
import type { CompilerSummary } from "../../generated/api/models/CompilerSummary";
import type { DirectoryEntryModel } from "../../generated/api/models/DirectoryEntryModel";
import type { StagedFile } from "../../generated/api/models/StagedFile";
import type { ActiveListing } from "../../generated/api/models/ActiveListing";
import type { ActiveFile } from "../../generated/api/models/ActiveFile";
import type { CompilerListResponse } from "../../generated/api/models/CompilerListResponse";

const STORE_ID = "machineconfig";

interface ProfilesTree {
  root: string;
  entries: DirectoryEntryModel[];
}

interface ActiveListingState {
  machine_name: string | null;
  files: ActiveFile[];
}

interface DeploySummary {
  message: string;
}

export interface MachineGenerateOutcome {
  status: "ok" | "conflict" | "error";
  machine: string | null;
  existing: string[];
}

export const useMachineConfigStore = defineStore(STORE_ID, () => {
  const consoleStore = useConsoleStore();

  // --- Reactive state ---------------------------------------------- //

  const compilers = ref<CompilerSummary[]>([]);
  const selectedCompilerId = ref<string>("");

  const profilesTree = reactive<ProfilesTree>({ root: "profiles", entries: [] });
  const selectedProfilePath = ref<string>("");

  const machinesTree = reactive<ProfilesTree>({ root: "machines", entries: [] });

  const stagedFiles = ref<StagedFile[]>([]);
  const stagedContents = reactive<Record<string, string>>({});

  const activeListing = reactive<ActiveListingState>({
    machine_name: null,
    files: [],
  });
  const activeContents = reactive<Record<string, string>>({});

  const confirmFlash = ref<boolean>(false);
  const isBusy = ref<boolean>(false);
  const lastDeploySummary = ref<DeploySummary | null>(null);

  // --- Derived state ----------------------------------------------- //

  const selectedCompiler = computed<CompilerSummary | null>(() =>
    compilers.value.find((c: CompilerSummary) => c.id === selectedCompilerId.value) || null,
  );

  const selectedProfile = computed<DirectoryEntryModel | null>(() => {
    const path = selectedProfilePath.value;
    if (!path) return null;
    return (
      profilesTree.entries.find(
        (e: DirectoryEntryModel) => e.path === path && e.kind === "file",
      ) || null
    );
  });

  const stagedTotalSize = computed<number>(() =>
    stagedFiles.value.reduce(
      (sum: number, f: StagedFile) => sum + (f.size_bytes || 0),
      0,
    ),
  );

  const activeTotalSize = computed<number>(() =>
    activeListing.files.reduce(
      (sum: number, f: ActiveFile) => sum + (f.size_bytes || 0),
      0,
    ),
  );

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

  async function loadCompilers(): Promise<void> {
    try {
      const response: CompilerListResponse = await machineconfigFacade.listCompilers() as CompilerListResponse;
      compilers.value = Array.isArray(
        (response as { compilers?: CompilerSummary[] }).compilers,
      )
        ? (response as { compilers: CompilerSummary[] }).compilers
        : [];
      if (!selectedCompilerId.value && compilers.value.length > 0) {
        selectedCompilerId.value = compilers.value[0].id;
      }
    } catch (error: unknown) {
      consoleStore.error(
        `Failed to list compilers: ${describeError(error)}`,
      );
    }
  }

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

  async function loadStaged(): Promise<void> {
    try {
      const response = await machineconfigFacade.listStaged();
      stagedFiles.value = Array.isArray(response) ? (response as StagedFile[]) : [];
      // Wipe the cached content map so a fresh staging run doesn't
      // serve stale previews.
      for (const key of Object.keys(stagedContents)) {
        delete stagedContents[key];
      }
    } catch (error: unknown) {
      const result = commandResultFromCaught(error, "load-staged");
      reportCommandFailure("load staged artifacts", result);
    }
  }

  async function loadActive(): Promise<void> {
    try {
      const response = (await machineconfigFacade.listActive()) as ActiveListing;
      activeListing.machine_name = response.machine_name ?? null;
      activeListing.files.splice(0, activeListing.files.length);
      for (const file of response.files || []) {
        activeListing.files.push(file);
      }
      for (const key of Object.keys(activeContents)) {
        delete activeContents[key];
      }
    } catch (error: unknown) {
      const result = commandResultFromCaught(error, "load-active");
      reportCommandFailure("load active artifacts", result);
    }
  }

  async function loadAll(): Promise<void> {
    await Promise.all([
      loadCompilers(),
      loadProfilesTree(),
      loadMachinesTree(),
      loadStaged(),
      loadActive(),
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

  // --- Compile / Deploy ------------------------------------------- //

  async function compile(
    profilePath: string,
  ): Promise<CommandResult | undefined> {
    if (!profilePath) return undefined;
    if (!selectedCompilerId.value) {
      consoleStore.warning("Pick a compiler before staging.");
      const result = CommandResult.failure("Pick a compiler before staging.");
      reportCommandFailure("compile", result);
      return result;
    }
    isBusy.value = true;
    const result = await machineconfigFacade.compileProfile({
      profile_path: profilePath,
      compiler_id: selectedCompilerId.value,
    });
    if (result.failed) {
      // Issue #99: the structured-error response from the compile
      // endpoint must surface as a toast so the operator sees the
      // reason without hunting in the console panel. The console
      // row is still written for the historical scrollback; the
      // popup is the new affordance.
      reportCommandFailure("compile", result);
    } else {
      // The compile response body is the typed ``CompileResponse``
      // (artifacts + compiler). Surface the count through the
      // console so the operator sees something happened even though
      // ``result.message`` only carries the wire status.
      // ``stagedFiles`` is repopulated below.
      // (The detailed artifact list is in ``result.message`` when
      // surfaced via ``commandId``; the original "Staged N
      // artifact(s) using C" line is preserved as an info row.)
      consoleStore.info(
        `Compile of ${profilePath} (${selectedCompilerId.value}) completed.`,
      );
      await loadStaged();
    }
    isBusy.value = false;
    return result;
  }

  async function deploy(): Promise<CommandResult | undefined> {
    if (stagedFiles.value.length === 0) {
      consoleStore.warning("Nothing to deploy — stage a profile first.");
      const result = CommandResult.failure("Nothing to deploy");
      reportCommandFailure("deploy", result);
      return result;
    }
    isBusy.value = true;
    const result = await machineconfigFacade.deployStaged({
      confirm_flash: confirmFlash.value,
    });
    if (result.failed) {
      reportCommandFailure("deploy", result);
    } else {
      const message = result.message || "Deploy complete.";
      lastDeploySummary.value = { message };
      consoleStore.success(message);
      await loadActive();
    }
    isBusy.value = false;
    return result;
  }

  async function readStagedFileContent(name: string): Promise<string | null> {
    try {
      const response = await machineconfigFacade.readStagedContent(name);
      const content = response.content || "";
      stagedContents[name] = content;
      return content;
    } catch (error: unknown) {
      consoleStore.error(`Failed to read staged ${name}: ${describeError(error)}`);
      return null;
    }
  }

  async function readActiveFileContent(name: string): Promise<string | null> {
    try {
      const response = await machineconfigFacade.readActiveContent(name);
      const content = response.content || "";
      activeContents[name] = content;
      return content;
    } catch (error: unknown) {
      consoleStore.error(`Failed to read active ${name}: ${describeError(error)}`);
      return null;
    }
  }

  // --- Public surface --------------------------------------------- //

  return {
    compilers,
    selectedCompilerId,
    selectedCompiler,
    profilesTree,
    selectedProfilePath,
    selectedProfile,
    machinesTree,
    stagedFiles,
    stagedContents,
    activeListing,
    activeContents,
    confirmFlash,
    isBusy,
    lastDeploySummary,
    stagedTotalSize,
    activeTotalSize,
    loadCompilers,
    loadProfilesTree,
    loadMachinesTree,
    loadStaged,
    loadActive,
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
    compile,
    deploy,
    readStagedFileContent,
    readActiveFileContent,
  };
});
