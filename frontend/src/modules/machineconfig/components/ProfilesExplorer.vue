<script setup>
// ProfilesExplorer — hierarchical file explorer for
// ``machine_config/profiles``. Renders a tree with folder / file icons
// and an inline "Compile / Generate" action button next to files
// whose first 8 KB contain the active compiler's ``source_marker``
// (typically ``#Start``).
//
// The component is intentionally dumb: it reads ``profilesTree`` and
// ``selectedProfilePath`` from the module store and dispatches
// ``compile`` / ``selectProfile`` / CRUD actions on the same store.
// The router-style panel layout (single column tree on the left,
// detail pane on the right) lives in the parent view.

import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../store.js";

const store = useMachineConfigStore();
const { profilesTree, selectedProfilePath, isBusy } = storeToRefs(store);

// ----------------------------------------------------------------- //
// Local UI state                                                      //
// ----------------------------------------------------------------- //

const expanded = ref(new Set());
const newEntryKind = ref("file"); // "file" | "folder"
const newEntryPath = ref("");

// Always expand the root so newly-created entries are immediately visible.
expanded.value.add("");

// ----------------------------------------------------------------- //
// Derived helpers                                                     //
// ----------------------------------------------------------------- //

function childrenOf(parent) {
  return profilesTree.value.entries.filter((entry) => entry.parent === parent);
}

function pathSegments(path) {
  return path ? path.split("/") : [];
}

function isExpanded(path) {
  return expanded.value.has(path);
}

function toggleExpanded(path) {
  if (expanded.value.has(path)) expanded.value.delete(path);
  else expanded.value.add(path);
}

// ----------------------------------------------------------------- //
// Actions                                                              //
// ----------------------------------------------------------------- //

function onSelectProfile(entry) {
  if (entry.kind !== "file") {
    toggleExpanded(entry.path);
    return;
  }
  store.selectProfile(entry.path);
}

async function onCompile(entry, event) {
  event.stopPropagation();
  store.selectProfile(entry.path);
  await store.compile(entry.path);
}

async function onDelete(entry) {
  // eslint-disable-next-line no-alert
  if (!window.confirm(`Delete ${entry.path}? This cannot be undone.`)) return;
  await store.deleteProfile(entry.path);
}

async function onCreate() {
  const path = newEntryPath.value.trim();
  if (!path) return;
  if (newEntryKind.value === "folder") {
    await store.createFolder(path);
  } else {
    await store.createFile(path);
  }
  newEntryPath.value = "";
}

// ----------------------------------------------------------------- //
// Tree walk                                                            //
// ----------------------------------------------------------------- //

const rootChildren = computed(() => childrenOf(null));

function iconFor(kind) {
  return kind === "folder" ? "📁" : "📄";
}

function depthOf(path) {
  return pathSegments(path).length;
}

function isFileMarked(entry) {
  return entry.kind === "file" && entry.has_marker;
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">📂</span> Profiles
      </h2>
      <span class="text-xs text-gray-400 font-mono">
        {{ profilesTree.entries.length }} entries
      </span>
    </div>

    <div class="p-3 flex flex-wrap gap-2 items-end border-b border-gray-700">
      <select
        v-model="newEntryKind"
        class="rounded bg-gray-900 border border-gray-600 text-gray-200 px-2 py-1 text-sm"
      >
        <option value="file">File</option>
        <option value="folder">Folder</option>
      </select>
      <input
        v-model="newEntryPath"
        type="text"
        placeholder="path/to/new/file.cfg"
        class="flex-1 min-w-[160px] rounded bg-gray-900 border border-gray-600 text-gray-200 px-2 py-1 text-sm font-mono"
        @keyup.enter="onCreate"
      />
      <button
        type="button"
        :disabled="isBusy || !newEntryPath.trim()"
        class="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 text-white text-sm font-semibold"
        @click="onCreate"
      >
        Create
      </button>
    </div>

    <div class="p-2 overflow-y-auto max-h-[480px]">
      <ul v-if="rootChildren.length > 0" class="space-y-1">
        <li
          v-for="entry in rootChildren"
          :key="entry.path || entry.name"
          class="space-y-1"
        >
          <div
            class="flex items-center gap-2 rounded px-2 py-1 cursor-pointer transition-colors"
            :class="[
              selectedProfilePath === entry.path
                ? 'bg-blue-600/30 border border-blue-500'
                : 'border border-transparent hover:bg-gray-700/40',
            ]"
            :style="{ marginLeft: `${depthOf(entry.path) * 12}px` }"
            @click="onSelectProfile(entry)"
          >
            <span class="text-base">{{ iconFor(entry.kind) }}</span>
            <span class="font-mono text-sm text-gray-200 truncate" :title="entry.path">
              {{ entry.name }}
            </span>
            <span
              v-if="isFileMarked(entry)"
              class="ml-1 px-1.5 py-0.5 rounded bg-purple-700/40 text-purple-200 text-[10px] font-semibold uppercase tracking-wider"
              title="Contains the compiler source marker (e.g. #Start)"
            >
              #Start
            </span>
            <span class="ml-auto flex items-center gap-1">
              <button
                v-if="isFileMarked(entry)"
                type="button"
                class="px-2 py-0.5 rounded bg-purple-600 hover:bg-purple-500 disabled:bg-purple-900 text-white text-xs font-semibold"
                :disabled="isBusy"
                @click="onCompile(entry, $event)"
              >
                ⚙ Compile
              </button>
              <button
                type="button"
                class="px-2 py-0.5 rounded bg-gray-600 hover:bg-red-500 text-white text-xs"
                :disabled="isBusy"
                @click.stop="onDelete(entry)"
                title="Delete"
              >
                ✕
              </button>
            </span>
          </div>

          <ul
            v-if="entry.kind === 'folder' && isExpanded(entry.path)"
            class="space-y-1 border-l border-gray-700/70 pl-2"
          >
            <li v-for="child in childrenOf(entry.path)" :key="child.path">
              <div
                class="flex items-center gap-2 rounded px-2 py-1 cursor-pointer transition-colors"
                :class="[
                  selectedProfilePath === child.path
                    ? 'bg-blue-600/30 border border-blue-500'
                    : 'border border-transparent hover:bg-gray-700/40',
                ]"
                :style="{ marginLeft: `${depthOf(child.path) * 8}px` }"
                @click="onSelectProfile(child)"
              >
                <span class="text-base">{{ iconFor(child.kind) }}</span>
                <span class="font-mono text-sm text-gray-200 truncate" :title="child.path">
                  {{ child.name }}
                </span>
                <span
                  v-if="isFileMarked(child)"
                  class="ml-1 px-1.5 py-0.5 rounded bg-purple-700/40 text-purple-200 text-[10px] font-semibold uppercase tracking-wider"
                >
                  #Start
                </span>
                <span class="ml-auto flex items-center gap-1">
                  <button
                    v-if="isFileMarked(child)"
                    type="button"
                    class="px-2 py-0.5 rounded bg-purple-600 hover:bg-purple-500 disabled:bg-purple-900 text-white text-xs font-semibold"
                    :disabled="isBusy"
                    @click="onCompile(child, $event)"
                  >
                    ⚙ Compile
                  </button>
                  <button
                    type="button"
                    class="px-2 py-0.5 rounded bg-gray-600 hover:bg-red-500 text-white text-xs"
                    :disabled="isBusy"
                    @click.stop="onDelete(child)"
                    title="Delete"
                  >
                    ✕
                  </button>
                </span>
              </div>

              <ul
                v-if="child.kind === 'folder' && isExpanded(child.path)"
                class="space-y-1 border-l border-gray-700/70 pl-2"
              >
                <li v-for="grand in childrenOf(child.path)" :key="grand.path">
                  <div
                    class="flex items-center gap-2 rounded px-2 py-1 cursor-pointer transition-colors"
                    :class="[
                      selectedProfilePath === grand.path
                        ? 'bg-blue-600/30 border border-blue-500'
                        : 'border border-transparent hover:bg-gray-700/40',
                    ]"
                    :style="{ marginLeft: `${depthOf(grand.path) * 4}px` }"
                    @click="onSelectProfile(grand)"
                  >
                    <span class="text-base">{{ iconFor(grand.kind) }}</span>
                    <span class="font-mono text-sm text-gray-200 truncate" :title="grand.path">
                      {{ grand.name }}
                    </span>
                    <span
                      v-if="isFileMarked(grand)"
                      class="ml-1 px-1.5 py-0.5 rounded bg-purple-700/40 text-purple-200 text-[10px] font-semibold uppercase tracking-wider"
                    >
                      #Start
                    </span>
                    <span class="ml-auto flex items-center gap-1">
                      <button
                        v-if="isFileMarked(grand)"
                        type="button"
                        class="px-2 py-0.5 rounded bg-purple-600 hover:bg-purple-500 disabled:bg-purple-900 text-white text-xs font-semibold"
                        :disabled="isBusy"
                        @click="onCompile(grand, $event)"
                      >
                        ⚙ Compile
                      </button>
                      <button
                        type="button"
                        class="px-2 py-0.5 rounded bg-gray-600 hover:bg-red-500 text-white text-xs"
                        :disabled="isBusy"
                        @click.stop="onDelete(grand)"
                        title="Delete"
                      >
                        ✕
                      </button>
                    </span>
                  </div>
                </li>
              </ul>
            </li>
          </ul>
        </li>
      </ul>
      <div v-else class="px-2 py-6 text-center text-gray-500 text-sm">
        No profiles found in <code class="text-gray-400">machine_config/profiles</code>.
        Create a new file or folder above to get started.
      </div>
    </div>
  </div>
</template>