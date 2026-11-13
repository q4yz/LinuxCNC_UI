<script setup lang="ts">
// Editor for a PageLayoutSetting: one row per panel — left / right column
// or hidden, and its place in the column (up / down). Each change saves.
import { computed } from "vue";
import { BaseButton } from "../../ui";
import BaseSelect from "../../ui/BaseSelect.vue";
import { movePanel, panelDef, shiftPanel, type PageLayout, type Placement } from "../../layout/pagePanels";
import type { PageLayoutSetting } from "../types/PageLayoutSetting";

const props = defineProps<{ setting: PageLayoutSetting }>();

const value = computed<PageLayout>(() => props.setting.value ?? props.setting.defaultValue);

const SECTIONS: { place: Placement; title: string }[] = [
  { place: "left", title: "Left column" },
  { place: "right", title: "Right column" },
  { place: "hidden", title: "Hidden" },
];

const save = (next: PageLayout) => void props.setting.save(next);
const move = (id: string, to: string | number) => save(movePanel(value.value, id, String(to) as Placement));
const shift = (id: string, delta: -1 | 1) => save(shiftPanel(value.value, id, delta));
</script>

<template>
  <div class="w-full space-y-3" :data-testid="`setting-${setting.key}`">
    <div v-for="section in SECTIONS" :key="section.place">
      <h4 class="mb-1 text-xs font-bold uppercase tracking-wider text-gray-400">{{ section.title }}</h4>
      <p v-if="value[section.place].length === 0" class="text-xs text-gray-500">—</p>
      <ul class="space-y-1">
        <li
            v-for="(id, index) in value[section.place]"
            :key="id"
            class="flex items-center gap-2 rounded border border-gray-700 bg-gray-900/50 px-2 py-1"
            :data-testid="`layout-${setting.page}-${id}`"
        >
          <span class="flex-1 text-sm text-gray-200">{{ panelDef(id)?.label ?? id }}</span>
          <template v-if="section.place !== 'hidden'">
            <BaseButton size="sm" variant="secondary" :disabled="index === 0" title="Move up" @click="shift(id, -1)">▲</BaseButton>
            <BaseButton size="sm" variant="secondary" :disabled="index === value[section.place].length - 1"
                        title="Move down" @click="shift(id, 1)">▼</BaseButton>
          </template>
          <BaseSelect :model-value="section.place" :label="`${panelDef(id)?.label ?? id} placement`" class="w-32"
                      @update:model-value="move(id, $event)">
            <option value="left">Left</option>
            <option value="right">Right</option>
            <option value="hidden">Hidden</option>
          </BaseSelect>
        </li>
      </ul>
    </div>
  </div>
</template>
