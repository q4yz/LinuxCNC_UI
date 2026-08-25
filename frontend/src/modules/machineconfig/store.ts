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

import manifest from "./manifest";
import { useConsoleStore } from "../../stores/console";
import {
  describeError as describeErrorShared,
  errorStatus,
  reportCommandFailure,
} from "../../core/error-format";
import { CommandResult } from "../../entities/common/CommandResult";
import { machineconfigFacade } from "../../facades/machineconfigFacade";

const STORE_ID = `module_${manifest.id}`;

export const useMachineConfigStore = defineStore(STORE_ID, () => {
  const consoleStore = useConsoleStore();

  // --- Reactive state ---------------------------------------------- //

  const compilers = ref([]);
  const selectedCompilerId = ref("");

  const profilesTree = reactive({ root: "profiles", entries: [] });
  const selectedProfilePath = ref("");

  const stagedFiles = ref([]);
  const stagedContents = reactive({});

  const activeListing = reactive({ machine_name: null, files: [] });
  const activeContents = reactive({});

  const confirmFlash = ref(false);
  const isBusy = ref(false);
  const lastDeploySummary = ref(null);

  // --- Derived state ----------------------------------------------- //

  const selectedCompiler = computed(() =>
    compilers.value.find((c) => c.id === selectedCompilerId.value) || null,
  );

  const selectedProfile = computed(() => {
    const path = selectedProfilePath.value;
    if (!path) return null;
    return (
      profilesTree.entries.find((e) => e.path === path && e.kind === "file") ||
      null
    );
  });

  const stagedTotalSize = computed(() =>
    stagedFiles.value.reduce((sum, f) => sum + (f.size_bytes || 0), 0),
  );

  const activeTotalSize = computed(() =>
    (activeListing.files || []).reduce(
      (sum, f) => sum + (f.size_bytes || 0),
      0,
    ),
  );

  // --- Error-mapping helper --------------------------------------- //
  //
  // The generated client throws ``ApiError`` on failure; plain
  // ``Error`` instances bubble through unchanged. The store wants
  // the same operator-readable message it used to get from the
  // legacy wrapper. Shared with ``modules/macros/store.js`` and
  // ``components/FileManager.vue`` via ``core/error-format.js`` so
  // a future envelope shape change lives in one place.
  const describeError = (error) =>
    describeErrorShared(error) || "Unknown error";

  function commandResultFromCaught(error: unknown, commandId: string): CommandResult {
    const result = CommandResult.failure(describeError(error), {
      commandId,
      statusCode: errorStatus(error),
    });
    return result;
  }

  // --- Loader actions --------------------------------------------- //
  //
  // Loader (read) actions keep the legacy void return shape — they
  // log their own errors via ``consoleStore.error`` because their
  // failure is informational (background refetch), not an operator
  // action.

  async function loadCompilers() {
    try {
      const response = await machineconfigFacade.listCompilers();
      compilers.value = Array.isArray(response.compilers)
        ? response.compilers
        : [];
      if (!selectedCompilerId.value && compilers.value.length > 0) {
        selectedCompilerId.value = compilers.value[0].id;
      }
    } catch (error) {
      consoleStore.error(
        `Failed to list compilers: ${describeError(error)}`,
      )
    }
  }

  async function loadProfilesTree() {
    try {
      const response = await machineconfigFacade.listProfiles();
      profilesTree.entries.splice(0, profilesTree.entries.length)
      for (const entry of response.entries || []) {
        profilesTree.entries.push(entry)
      }
    } catch (error) {
      const result = commandResultFromCaught(error, "load-profiles-tree");
      reportCommandFailure("load profiles tree", result);
    }
  }

  async function loadStaged() {
    try {
      stagedFiles.value = await machineconfigFacade.listStaged();
      // Wipe the cached content map so a fresh staging run doesn't
      // serve stale previews.
      for (const key of Object.keys(stagedContents)) {
        delete stagedContents[key]
      }
    } catch (error) {
      const result = commandResultFromCaught(error, "load-staged");
      reportCommandFailure("load staged artifacts", result);
    }
  }

  async function loadActive() {
    try {
      const response = await machineconfigFacade.listActive();
      activeListing.machine_name = response.machine_name || null
      activeListing.files.splice(0, activeListing.files.length)
      for (const file of response.files || []) {
        activeListing.files.push(file)
      }
      for (const key of Object.keys(activeContents)) {
        delete activeContents[key]
      }
    } catch (error) {
      const result = commandResultFromCaught(error, "load-active");
      reportCommandFailure("load active artifacts", result);
    }
  }

  async function loadAll() {
    await Promise.all([
      loadCompilers(),
      loadProfilesTree(),
      loadStaged(),
      loadActive(),
    ])
  }

  // --- Profile actions -------------------------------------------- //

  function selectProfile(path) {
    selectedProfilePath.value = path || ""
  }

  async function readProfileContent(path) {
    try {
      const response = await machineconfigFacade.readProfile(path);
      return response.content || ""
    } catch (error) {
      consoleStore.error(`Failed to read ${path}: ${describeError(error)}`)
      return null
    }
  }

  async function saveProfile(path, content): Promise<CommandResult> {
    isBusy.value = true
    const result = await machineconfigFacade.writeProfile(path, content);
    if (result.failed) {
      reportCommandFailure(`save profile ${path}`, result);
    } else {
      consoleStore.success(`Saved ${path}`)
      await loadProfilesTree()
    }
    isBusy.value = false
    return result;
  }

  async function createFolder(path): Promise<CommandResult> {
    isBusy.value = true
    const result = await machineconfigFacade.createFolder(path);
    if (result.failed) {
      reportCommandFailure(`create folder ${path}`, result);
    } else {
      consoleStore.success(`Created folder ${path}`)
      await loadProfilesTree()
    }
    isBusy.value = false
    return result;
  }

  async function createFile(path): Promise<CommandResult> {
    isBusy.value = true
    const result = await machineconfigFacade.createFile(path);
    if (result.failed) {
      reportCommandFailure(`create file ${path}`, result);
    } else {
      consoleStore.success(`Created file ${path}`)
      await loadProfilesTree()
    }
    isBusy.value = false
    return result;
  }

  async function uploadProfiles(directory, files): Promise<CommandResult> {
    isBusy.value = true
    const result = await machineconfigFacade.uploadProfile(directory, files);
    if (result.failed) {
      reportCommandFailure("upload profiles", result);
    } else {
      consoleStore.success(`Uploaded ${files.length} profile file(s)`)
      await loadProfilesTree()
    }
    isBusy.value = false
    return result;
  }

  async function renameProfile(source, destination): Promise<CommandResult> {
    isBusy.value = true
    const result = await machineconfigFacade.renameProfile(source, destination);
    if (result.failed) {
      reportCommandFailure(`rename ${source} -> ${destination}`, result);
    } else {
      consoleStore.success(`Renamed ${source} -> ${destination}`)
      if (selectedProfilePath.value === source) {
        selectedProfilePath.value = destination
      }
      await loadProfilesTree()
    }
    isBusy.value = false
    return result;
  }

  async function deleteProfile(path): Promise<CommandResult> {
    isBusy.value = true
    const result = await machineconfigFacade.deleteProfile(path);
    if (result.failed) {
      reportCommandFailure(`delete profile ${path}`, result);
    } else {
      consoleStore.success(`Deleted ${path}`)
      if (selectedProfilePath.value === path) {
        selectedProfilePath.value = ""
      }
      await loadProfilesTree()
    }
    isBusy.value = false
    return result;
  }

  // --- Compile / Deploy ------------------------------------------- //

  async function compile(profilePath): Promise<CommandResult | undefined> {
    if (!profilePath) return undefined;
    if (!selectedCompilerId.value) {
      consoleStore.warning("Pick a compiler before staging.")
      const result = CommandResult.failure("Pick a compiler before staging.");
      reportCommandFailure("compile", result);
      return result;
    }
    isBusy.value = true
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
    isBusy.value = false
    return result;
  }

  async function deploy(): Promise<CommandResult | undefined> {
    if (stagedFiles.value.length === 0) {
      consoleStore.warning("Nothing to deploy — stage a profile first.")
      const result = CommandResult.failure("Nothing to deploy");
      reportCommandFailure("deploy", result);
      return result;
    }
    isBusy.value = true
    const result = await machineconfigFacade.deployStaged({
      confirm_flash: confirmFlash.value,
    });
    if (result.failed) {
      reportCommandFailure("deploy", result);
    } else {
      const message = result.message || "Deploy complete.";
      lastDeploySummary.value = { message };
      consoleStore.success(message)
      await loadActive()
    }
    isBusy.value = false
    return result;
  }

  async function readStagedFileContent(name) {
    try {
      const response = await machineconfigFacade.readStagedContent(name);
      stagedContents[name] = response.content || ""
      return response.content || ""
    } catch (error) {
      consoleStore.error(`Failed to read staged ${name}: ${describeError(error)}`)
      return null
    }
  }

  async function readActiveFileContent(name) {
    try {
      const response = await machineconfigFacade.readActiveContent(name);
      activeContents[name] = response.content || ""
      return response.content || ""
    } catch (error) {
      consoleStore.error(`Failed to read active ${name}: ${describeError(error)}`)
      return null
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
    compile,
    deploy,
    readStagedFileContent,
    readActiveFileContent,
  }
})
