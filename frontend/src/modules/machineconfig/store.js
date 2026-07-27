// Machineconfig module Pinia store.
//
// Owns the module's reactive state — the profiles tree, the available
// compilers, the staged / active file listings, the currently selected
// compiler, and the deployment-flow toggles (e.g. ``confirmFlash``).
//
// The store id follows the ``module_${manifest.id}`` pattern from
// ``.agent/contracts/frontend-module.md`` § 5 so the
// ``scripts/check-store-ids.mjs`` lint script keeps passing.
//
// We deliberately do NOT pinia-cache the result of every endpoint —
// the backend is the source of truth for staged / active / profiles
// listings, and Vue components that need a value call the store
// action which re-reads. This keeps the store small and the operator
// always sees the truth after a refetch.

import { defineStore, storeToRefs } from "pinia";
import { computed, reactive, ref } from "vue";

import manifest from "./manifest.js";
import * as api from "./services/api.js";
import { useConsoleStore } from "../../stores/console.js";

const STORE_ID = `module_${manifest.id}`;

export const useMachineConfigStore = defineStore(STORE_ID, () => {
  const consoleStore = useConsoleStore();

  // ----------------------------------------------------------------- //
  // Reactive state                                                     //
  // ----------------------------------------------------------------- //

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

  // ----------------------------------------------------------------- //
  // Derived state                                                      //
  // ----------------------------------------------------------------- //

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

  // ----------------------------------------------------------------- //
  // Loader actions                                                      //
  // ----------------------------------------------------------------- //

  async function loadCompilers() {
    try {
      const response = await api.listCompilers();
      compilers.value = Array.isArray(response.compilers) ? response.compilers : [];
      if (!selectedCompilerId.value && compilers.value.length > 0) {
        selectedCompilerId.value = compilers.value[0].id;
      }
    } catch (error) {
      consoleStore.addMessage(`Failed to list compilers: ${error.message}`, "error");
    }
  }

  async function loadProfilesTree() {
    try {
      const response = await api.listProfilesTree();
      profilesTree.entries.splice(0, profilesTree.entries.length);
      for (const entry of response.entries || []) {
        profilesTree.entries.push(entry);
      }
    } catch (error) {
      consoleStore.addMessage(`Failed to load profiles: ${error.message}`, "error");
    }
  }

  async function loadStaged() {
    try {
      stagedFiles.value = await api.listStaged();
      // Wipe the cached content map so a fresh staging run doesn't
      // serve stale previews.
      for (const key of Object.keys(stagedContents)) {
        delete stagedContents[key];
      }
    } catch (error) {
      consoleStore.addMessage(`Failed to load staged artifacts: ${error.message}`, "error");
    }
  }

  async function loadActive() {
    try {
      const response = await api.listActive();
      activeListing.machine_name = response.machine_name || null;
      activeListing.files.splice(0, activeListing.files.length);
      for (const file of response.files || []) {
        activeListing.files.push(file);
      }
      for (const key of Object.keys(activeContents)) {
        delete activeContents[key];
      }
    } catch (error) {
      consoleStore.addMessage(`Failed to load active artifacts: ${error.message}`, "error");
    }
  }

  async function loadAll() {
    await Promise.all([
      loadCompilers(),
      loadProfilesTree(),
      loadStaged(),
      loadActive(),
    ]);
  }

  // ----------------------------------------------------------------- //
  // Profile actions                                                     //
  // ----------------------------------------------------------------- //

  function selectProfile(path) {
    selectedProfilePath.value = path || "";
  }

  async function readProfileContent(path) {
    try {
      const response = await api.readProfile(path);
      return response.content || "";
    } catch (error) {
      consoleStore.error(`Failed to read ${path}: ${error.message}`);
      return null;
    }
  }

  async function saveProfile(path, content) {
    isBusy.value = true;
    try {
      await api.saveProfile(path, content);
      consoleStore.success(`Saved ${path}`);
      await loadProfilesTree();
    } catch (error) {
      consoleStore.error(`Failed to save ${path}: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  async function createFolder(path) {
    isBusy.value = true;
    try {
      await api.createFolder(path);
      consoleStore.success(`Created folder ${path}`);
      await loadProfilesTree();
    } catch (error) {
      consoleStore.error(`Folder create failed: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  async function createFile(path) {
    isBusy.value = true;
    try {
      await api.createFile(path);
      consoleStore.success(`Created file ${path}`);
      await loadProfilesTree();
    } catch (error) {
      consoleStore.error(`File create failed: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  async function uploadProfiles(directory, files) {
    isBusy.value = true;
    try {
      for (const file of files) {
        const path = [directory, file.name].filter(Boolean).join("/");
        await api.uploadProfile(path, file);
      }
      consoleStore.success(`Uploaded ${files.length} profile file(s)`);
      await loadProfilesTree();
    } catch (error) {
      consoleStore.error(`Upload failed: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  async function renameProfile(source, destination) {
    isBusy.value = true;
    try {
      await api.renameProfile(source, destination);
      consoleStore.success(`Renamed ${source} -> ${destination}`);
      if (selectedProfilePath.value === source) {
        selectedProfilePath.value = destination;
      }
      await loadProfilesTree();
    } catch (error) {
      consoleStore.error(`Rename failed: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  async function deleteProfile(path) {
    isBusy.value = true;
    try {
      await api.deleteProfile(path);
      consoleStore.success(`Deleted ${path}`);
      if (selectedProfilePath.value === path) {
        selectedProfilePath.value = "";
      }
      await loadProfilesTree();
    } catch (error) {
      consoleStore.error(`Delete failed: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  // ----------------------------------------------------------------- //
  // Compile / Deploy                                                    //
  // ----------------------------------------------------------------- //

  async function compile(profilePath) {
    if (!profilePath) return;
    if (!selectedCompilerId.value) {
      consoleStore.warning("Pick a compiler before staging.");
      return;
    }
    isBusy.value = true;
    try {
      const response = await api.compileProfile(
        profilePath,
        selectedCompilerId.value,
      );
      consoleStore.success(
        `Staged ${response.artifacts.length} artifact(s) using ${response.compiler}.`
      );
      await loadStaged();
    } catch (error) {
      consoleStore.error(`Compile failed: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  async function deploy() {
    if (stagedFiles.value.length === 0) {
      consoleStore.warning("Nothing to deploy — stage a profile first.");
      return;
    }
    isBusy.value = true;
    try {
      const response = await api.deployStaged({ confirmFlash: confirmFlash.value });
      lastDeploySummary.value = response;
      consoleStore.success(response.message || "Deploy complete.");
      await loadActive();
    } catch (error) {
      consoleStore.error(`Deploy failed: ${error.message}`);
    } finally {
      isBusy.value = false;
    }
  }

  async function readStagedFileContent(name) {
    try {
      const response = await api.readStagedContent(name);
      stagedContents[name] = response.content || "";
      return response.content || "";
    } catch (error) {
      consoleStore.error(`Failed to read staged ${name}: ${error.message}`);
      return null;
    }
  }

  async function readActiveFileContent(name) {
    try {
      const response = await api.readActiveContent(name);
      activeContents[name] = response.content || "";
      return response.content || "";
    } catch (error) {
      consoleStore.error(`Failed to read active ${name}: ${error.message}`);
      return null;
    }
  }

  // ----------------------------------------------------------------- //
  // Public surface                                                     //
  // ----------------------------------------------------------------- //

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
  };
});

/**
 * Helper that wraps :func:`storeToRefs` so callers can destructure the
 * reactive state without losing reactivity. See the machine module
 * for the canonical pattern.
 *
 * @returns {{store: import('pinia').Store, ...import('vue').ToRefs<...>}}
 */
export function useMachineConfigRefs() {
  const store = useMachineConfigStore();
  return { store, ...storeToRefs(store) };
}

export default useMachineConfigStore;