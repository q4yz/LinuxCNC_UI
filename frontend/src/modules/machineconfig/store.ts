// Machineconfig module Pinia store. Owns the profiles tree, the
// compilers, the staged / active listings, the selected compiler,
// and the deployment toggles. The backend is the source of truth —
// we re-fetch per action rather than caching, so operators always
// see current values after a refetch. See ``.agent/STATE.md`` § 2.
//
// All HTTP calls go through the OpenAPI-generated
// ``ModulesMachineconfigService``. The legacy ``services/api.js``
// wrapper has been deleted; the generated client is the single
// source of HTTP truth for this store.

import { defineStore } from "pinia";
import { computed, reactive, ref } from "vue";

import { ModulesMachineconfigService } from "../../../generated/api/index.ts";
import manifest from "./manifest";
import { useConsoleStore } from "../../stores/console";
import { describeError as describeErrorShared } from "../../core/error-format";

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
  // legacy wrapper.
  //
  // Shared with ``modules/macros/store.js`` and
  // ``components/FileManager.vue`` via ``core/error-format.js`` so
  // a future envelope shape change lives in one place. The wrapper
  // here preserves the legacy "Unknown error" fallback for any
  // falsy input so existing log messages don't regress to empty.
  const describeError = (error) =>
    describeErrorShared(error) || "Unknown error";

  // --- Loader actions --------------------------------------------- //

  async function loadCompilers() {
    try {
      const response = await ModulesMachineconfigService
        .listCompilersApiV1ModulesMachineconfigCompilersGet()
      compilers.value = Array.isArray(response.compilers) ? response.compilers : []
      if (!selectedCompilerId.value && compilers.value.length > 0) {
        selectedCompilerId.value = compilers.value[0].id
      }
    } catch (error) {
      consoleStore.error(
        `Failed to list compilers: ${describeError(error)}`,
      )
    }
  }

  async function loadProfilesTree() {
    try {
      const response = await ModulesMachineconfigService
        .getProfilesTreeApiV1ModulesMachineconfigProfilesTreeGet()
      profilesTree.entries.splice(0, profilesTree.entries.length)
      for (const entry of response.entries || []) {
        profilesTree.entries.push(entry)
      }
    } catch (error) {
      consoleStore.error(
        `Failed to load profiles: ${describeError(error)}`,
      )
    }
  }

  async function loadStaged() {
    try {
      stagedFiles.value = await ModulesMachineconfigService
        .listStagedApiV1ModulesMachineconfigStagedGet()
      // Wipe the cached content map so a fresh staging run doesn't
      // serve stale previews.
      for (const key of Object.keys(stagedContents)) {
        delete stagedContents[key]
      }
    } catch (error) {
      consoleStore.error(
        `Failed to load staged artifacts: ${describeError(error)}`,
      )
    }
  }

  async function loadActive() {
    try {
      const response = await ModulesMachineconfigService
        .listActiveApiV1ModulesMachineconfigActiveGet()
      activeListing.machine_name = response.machine_name || null
      activeListing.files.splice(0, activeListing.files.length)
      for (const file of response.files || []) {
        activeListing.files.push(file)
      }
      for (const key of Object.keys(activeContents)) {
        delete activeContents[key]
      }
    } catch (error) {
      consoleStore.error(
        `Failed to load active artifacts: ${describeError(error)}`,
      )
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
      const response = await ModulesMachineconfigService
        .readProfileApiV1ModulesMachineconfigProfilesContentGet(path)
      return response.content || ""
    } catch (error) {
      consoleStore.error(`Failed to read ${path}: ${describeError(error)}`)
      return null
    }
  }

  async function saveProfile(path, content) {
    isBusy.value = true
    try {
      await ModulesMachineconfigService
        .saveProfileApiV1ModulesMachineconfigProfilesContentPut(path, { content })
      consoleStore.success(`Saved ${path}`)
      await loadProfilesTree()
    } catch (error) {
      consoleStore.error(`Failed to save ${path}: ${describeError(error)}`)
    } finally {
      isBusy.value = false
    }
  }

  async function createFolder(path) {
    isBusy.value = true
    try {
      await ModulesMachineconfigService
        .createFolderApiV1ModulesMachineconfigProfilesFolderPost({ path })
      consoleStore.success(`Created folder ${path}`)
      await loadProfilesTree()
    } catch (error) {
      consoleStore.error(`Folder create failed: ${describeError(error)}`)
    } finally {
      isBusy.value = false
    }
  }

  async function createFile(path) {
    isBusy.value = true
    try {
      await ModulesMachineconfigService
        .createFileApiV1ModulesMachineconfigProfilesFilePost({ path })
      consoleStore.success(`Created file ${path}`)
      await loadProfilesTree()
    } catch (error) {
      consoleStore.error(`File create failed: ${describeError(error)}`)
    } finally {
      isBusy.value = false
    }
  }

  async function uploadProfiles(directory, files) {
    isBusy.value = true
    try {
      for (const file of files) {
        const path = [directory, file.name].filter(Boolean).join("/")
        // The codegen types ``Body_upload_profile..._post.file`` as
        // ``string``, but ``request.ts::isBlob`` accepts ``File`` at
        // runtime. Pass the raw ``File`` so multipart upload works.
        await ModulesMachineconfigService
          .uploadProfileApiV1ModulesMachineconfigProfilesUploadPost(path, {
            file: file,
          })
      }
      consoleStore.success(`Uploaded ${files.length} profile file(s)`)
      await loadProfilesTree()
    } catch (error) {
      consoleStore.error(`Upload failed: ${describeError(error)}`)
    } finally {
      isBusy.value = false
    }
  }

  async function renameProfile(source, destination) {
    isBusy.value = true
    try {
      await ModulesMachineconfigService
        .renameProfileApiV1ModulesMachineconfigProfilesRenamePut({
          source,
          destination,
        })
      consoleStore.success(`Renamed ${source} -> ${destination}`)
      if (selectedProfilePath.value === source) {
        selectedProfilePath.value = destination
      }
      await loadProfilesTree()
    } catch (error) {
      consoleStore.error(`Rename failed: ${describeError(error)}`)
    } finally {
      isBusy.value = false
    }
  }

  async function deleteProfile(path) {
    isBusy.value = true
    try {
      await ModulesMachineconfigService
        .deleteProfileApiV1ModulesMachineconfigProfilesEntryDelete(path)
      consoleStore.success(`Deleted ${path}`)
      if (selectedProfilePath.value === path) {
        selectedProfilePath.value = ""
      }
      await loadProfilesTree()
    } catch (error) {
      consoleStore.error(`Delete failed: ${describeError(error)}`)
    } finally {
      isBusy.value = false
    }
  }

  // --- Compile / Deploy ------------------------------------------- //

  async function compile(profilePath) {
    if (!profilePath) return
    if (!selectedCompilerId.value) {
      consoleStore.warning("Pick a compiler before staging.")
      return
    }
    isBusy.value = true
    try {
      // The generated client expects a single ``CompileRequest`` body
      // object — not two positional arguments. Passing the path and
      // compiler id as separate arguments makes ``requestBody`` a
      // string, which FastAPI rejects with a 422 Pydantic validation
      // error ("Input should be a valid dictionary or object to
      // extract fields from") before the endpoint even runs.
      const response = await ModulesMachineconfigService
        .compileProfileApiV1ModulesMachineconfigCompilePost({
          profile_path: profilePath,
          compiler_id: selectedCompilerId.value,
        })
      consoleStore.success(
        `Staged ${response.artifacts.length} artifact(s) using ${response.compiler}.`,
      )
      await loadStaged()
    } catch (error) {
      // Issue #99: the structured-error response from the compile
      // endpoint must surface as a toast so the operator sees the
      // reason without hunting in the console panel. The console
      // row is still written for the historical scrollback; the
      // popup is the new affordance.
      consoleStore.error(
        `Compile failed: ${describeError(error)}`,
        { popup: true, title: "Compile failed" },
      )
    } finally {
      isBusy.value = false
    }
  }

  async function deploy() {
    if (stagedFiles.value.length === 0) {
      consoleStore.warning("Nothing to deploy — stage a profile first.")
      return
    }
    isBusy.value = true
    try {
      // The openapi-generated client expects the snake_case field
      // name ``confirm_flash`` (the openapi schema preserves the
      // backend's Pydantic field name). Sending ``confirmFlash``
      // instead dropped the value on the wire and the backend
      // received ``confirm_flash: undefined``, which the deploy
      // endpoint rejects with HTTP 400.
      const response = await ModulesMachineconfigService
        .deployStagedApiV1ModulesMachineconfigDeployPost({
          confirm_flash: confirmFlash.value,
        })
      lastDeploySummary.value = response
      consoleStore.success(response.message || "Deploy complete.")
      await loadActive()
    } catch (error) {
      consoleStore.error(`Deploy failed: ${describeError(error)}`)
    } finally {
      isBusy.value = false
    }
  }

  async function readStagedFileContent(name) {
    try {
      const response = await ModulesMachineconfigService
        .readStagedApiV1ModulesMachineconfigStagedContentNameGet(name)
      stagedContents[name] = response.content || ""
      return response.content || ""
    } catch (error) {
      consoleStore.error(`Failed to read staged ${name}: ${describeError(error)}`)
      return null
    }
  }

  async function readActiveFileContent(name) {
    try {
      const response = await ModulesMachineconfigService
        .readActiveApiV1ModulesMachineconfigActiveContentNameGet(name)
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