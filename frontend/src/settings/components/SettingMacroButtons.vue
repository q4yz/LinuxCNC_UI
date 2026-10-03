<script setup lang="ts">
// Editor for a MacroButtonsSetting — the existing MacroButtonEditor
// (one row per slot, commits on change), persisted through the setting.
import { MacroButtonEditor } from "../../ui";
import type { MacroButtonDescriptor } from "../../ui/macroButtonTypes";
import type { MacroButtonsSetting } from "../types/MacroButtonsSetting";

const props = defineProps<{ setting: MacroButtonsSetting }>();

const onUpdate = (next: MacroButtonDescriptor[]) => void props.setting.save(next);
</script>

<template>
  <div class="w-full">
    <MacroButtonEditor
        :model-value="setting.value ?? []"
        :slots="setting.slots"
        description=""
        @update:model-value="onUpdate"
    />
  </div>
</template>
