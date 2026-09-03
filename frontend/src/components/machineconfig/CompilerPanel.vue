<script setup lang="ts">
// @ts-nocheck
// @deprecated Deprecated component — excluded from TS-migration fixes.
// Do not add features here; the component is slated for removal.
//
// CompilerPanel — picks the active Configuration Compiler and
// triggers a compile on the currently selected profile.
//
// The panel pairs with the inline "Compile" buttons in the
// :class:`ProfilesExplorer` — clicking one there also fires
// ``store.compile(profilePath)``, so this panel is mostly for
// operators who want to (re)compile via the dropdown instead of
// per-file.

import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../../stores/machineconfigStore";
import { BaseButton } from "../../ui/index.ts";
import BaseCard from "../../ui/BaseCard.vue";
import BaseSelect from "../../ui/BaseSelect.vue";

const store = useMachineConfigStore();
const { compilers, selectedCompilerId, selectedCompiler, selectedProfilePath, isBusy } =
  storeToRefs(store);

const profileLabel = computed(() => selectedProfilePath.value || "(no profile selected)");

async function onCompile() {
  if (!selectedProfilePath.value) {
    // eslint-disable-next-line no-alert
    window.alert("Select a profile in the explorer first.");
    return;
  }
  await store.compile(selectedProfilePath.value);
}
</script>

<template>
  <BaseCard title="⚙️ Configuration Compiler">
    <div class="space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div class="md:col-span-2">
          <label class="block text-xs uppercase tracking-wider text-gray-400 mb-1">
            Active Compiler
          </label>
          <BaseSelect v-model="selectedCompilerId" class="w-full">
            <option disabled value="">Select a compiler...</option>
            <option v-for="compiler in compilers" :key="compiler.id" :value="compiler.id">
              {{ compiler.title }} ({{ compiler.id }})
            </option>
          </BaseSelect>
          <p
            v-if="selectedCompiler"
            class="mt-1 text-[11px] text-gray-400 font-mono"
          >
            Source marker: <code>{{ selectedCompiler.source_marker || "(none)" }}</code>
          </p>
        </div>
        <BaseButton
          variant="primary"
          class="w-full"
          :disabled="isBusy || !selectedCompiler || !selectedProfilePath"
          @click="onCompile"
        >
          {{ isBusy ? 'Compiling…' : 'Compile Selected' }}
        </BaseButton>
      </div>

      <p class="text-xs text-gray-400">
        Active profile:
        <code class="text-gray-300 font-mono">{{ profileLabel }}</code>
      </p>
    </div>
  </BaseCard>
</template>