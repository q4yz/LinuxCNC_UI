<script setup>
import { onMounted, ref } from 'vue';
import ConfigEditor from '../components/ConfigEditor.vue';
import DebugPanel from '../components/DebugPanel.vue';
import UpdateManager from '../components/UpdateManager.vue';
import { useMachineConfigStore } from '../modules/machineconfig/store.js';
import ProfilesExplorer from '../modules/machineconfig/components/ProfilesExplorer.vue';
import CompilerPanel from '../modules/machineconfig/components/CompilerPanel.vue';
import CompiledOutputViewer from '../modules/machineconfig/components/CompiledOutputViewer.vue';
import DeploymentPanel from '../modules/machineconfig/components/DeploymentPanel.vue';
import ActivePanel from '../modules/machineconfig/components/ActivePanel.vue';

const machineConfigStore = useMachineConfigStore();
const editorPath = ref('');
const editorContent = ref('');

async function openEditor(path) {
  const content = await machineConfigStore.readProfileContent(path);
  if (content === null) return;
  editorPath.value = path;
  editorContent.value = content;
}

async function saveEditor() {
  await machineConfigStore.saveProfile(editorPath.value, editorContent.value);
}

// 1. New function to handle saving and immediately closing
async function saveAndCloseEditor() {
  await saveEditor();
  editorPath.value = '';
}

// 2. New function to confirm before closing
function confirmClose() {
  if (window.confirm("Are you sure you want to close? Any unsaved changes will be lost.")) {
    editorPath.value = '';
  }
}

onMounted(() => {
  void machineConfigStore.loadAll();
});
</script>

<template>
  <div v-if="editorPath" class="fixed inset-0 z-50 flex flex-col bg-gray-900">
    <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3">
      <span class="font-mono text-blue-300">Editing {{ editorPath }}</span>
      <div class="flex gap-2">
        <!-- 3. Updated buttons wired to the new functions -->
        <button type="button" class="rounded bg-gray-600 px-4 py-2 font-semibold hover:bg-gray-500" @click="confirmClose">Close</button>
        <button type="button" class="rounded bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-500" @click="saveAndCloseEditor">Save & Close</button>
        <button type="button" class="rounded bg-green-600 px-4 py-2 font-semibold hover:bg-green-500" @click="saveEditor">Save</button>
      </div>
    </div>
    <div class="min-h-0 flex-1">
      <!-- 4. Fixed read-only="false" and added mode="profile" -->
      <ConfigEditor v-model="editorContent" :filename="editorPath" :read-only="false" mode="profile" />
    </div>
  </div>
  <div v-else class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12">
    <section class="space-y-6 xl:col-span-4">
      <UpdateManager />

      <DebugPanel />
    </section>

    <section class="space-y-6 xl:col-span-8">
      <CompilerPanel />

      <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ProfilesExplorer @edit="openEditor" />

        <div class="space-y-6">
          <CompiledOutputViewer />
          <DeploymentPanel />
        </div>
      </div>

      <ActivePanel />
    </section>
  </div>
</template>