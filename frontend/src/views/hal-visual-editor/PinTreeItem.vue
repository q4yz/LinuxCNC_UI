<script setup lang="ts">
// One row of the HAL pin picker tree — recursive: a folder renders
// its children via more `PinTreeItem`s, a leaf is the pin itself.
// See ./pinTree.ts for how the tree and the match-highlighting are
// built.

import { computed } from "vue";
import { Icon } from "../../ui/index.ts";
import { folderContainsSuffix, lastSegment } from "./pinTree";
import type { PinTreeNode } from "./pinTree";
import type { HalPin, PinType } from "./types";

defineOptions({ name: "PinTreeItem" });

const props = defineProps<{
  node: PinTreeNode;
  /** Folder paths the operator has manually toggled open. */
  expanded: Set<string>;
  /** Folder paths forced open (active search, or a name-matched pin inside). */
  autoExpand: Set<string>;
  /** The connected pin's last name segment, e.g. "step" — null when
   *  the block's other side isn't wired yet, so nothing is matched. */
  matchSuffix: string | null;
  selectedIds: Set<string>;
  depth: number;
}>();

const emit = defineEmits<{ pick: [pin: HalPin]; toggle: [path: string] }>();

const TYPE_BADGE: Record<Exclude<PinType, "auto">, string> = {
  bit: "bg-green-900/60 text-green-300 border border-green-700",
  float: "bg-blue-900/60 text-blue-300 border border-blue-700",
  s32: "bg-amber-900/60 text-amber-300 border border-amber-700",
  u32: "bg-purple-900/60 text-purple-300 border border-purple-700",
};

const isOpen = computed(() => {
  if (props.node.kind !== "folder") return false;
  return props.autoExpand.has(props.node.path) || props.expanded.has(props.node.path);
});

// A folder lights up when a name-matched pin is somewhere inside it,
// so the operator can spot the right branch before drilling in.
const hasMatch = computed(() => {
  if (props.node.kind !== "folder") return false;
  return folderContainsSuffix(props.node, props.matchSuffix);
});

const isSuffixMatch = computed(() => {
  if (props.node.kind !== "pin" || !props.matchSuffix) return false;
  return lastSegment(props.node.pin.fullName) === props.matchSuffix;
});

const isSelected = computed(
  () => props.node.kind === "pin" && props.selectedIds.has(props.node.pin.id),
);

const indent = computed(() => `${props.depth * 14 + 6}px`);

function onFolderClick() {
  if (props.node.kind === "folder") emit("toggle", props.node.path);
}
</script>

<template>
  <div v-if="node.kind === 'folder'">
    <button
      type="button"
      class="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-xs font-semibold uppercase tracking-wide transition-colors hover:bg-gray-800"
      :class="hasMatch ? 'text-amber-400' : 'text-gray-400'"
      :style="{ paddingLeft: indent }"
      :data-test="`hal-pin-folder-${node.path}`"
      @click="onFolderClick"
    >
      <Icon name="chevronDown" class="h-3 w-3 shrink-0 transition-transform" :class="isOpen ? '' : '-rotate-90'" />
      <span class="truncate">{{ node.segment }}</span>
      <span
        v-if="hasMatch"
        class="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
        title="Contains a pin with a matching name"
      />
    </button>
    <div v-if="isOpen">
      <PinTreeItem
        v-for="child in node.children"
        :key="child.kind === 'folder' ? `f:${child.path}` : `p:${child.pin.id}`"
        :node="child"
        :expanded="expanded"
        :auto-expand="autoExpand"
        :match-suffix="matchSuffix"
        :selected-ids="selectedIds"
        :depth="depth + 1"
        @pick="emit('pick', $event)"
        @toggle="emit('toggle', $event)"
      />
    </div>
  </div>

  <button
    v-else
    type="button"
    class="flex w-full items-center justify-between gap-2 rounded-md border py-1.5 pr-2 text-left transition-colors"
    :class="[
      isSelected ? 'border-green-600 bg-green-950/40' : 'border-gray-700 bg-gray-900 hover:border-gray-500',
      isSuffixMatch && !isSelected ? 'ring-1 ring-amber-500/70' : '',
    ]"
    :style="{ paddingLeft: indent }"
    :title="node.pin.description"
    :data-test="`hal-pin-leaf-${node.pin.id}`"
    @click="emit('pick', node.pin)"
  >
    <span class="min-w-0">
      <span class="block truncate font-mono text-sm">{{ node.segment }}</span>
      <span v-if="node.pin.description || node.pin.componentName" class="block truncate text-[11px] text-gray-500">
        {{ node.pin.componentName ? node.pin.componentName + " · " : "" }}{{ node.pin.description }}
      </span>
    </span>
    <span class="flex shrink-0 items-center gap-1.5">
      <Icon v-if="isSelected" name="check" class="h-3.5 w-3.5 text-green-400" />
      <span
        v-if="isSuffixMatch"
        class="h-1.5 w-1.5 rounded-full bg-amber-400"
        title="Same name pattern as the connected side"
      />
      <span class="rounded px-1.5 py-0.5 text-xs font-mono" :class="TYPE_BADGE[node.pin.type]">{{ node.pin.type }}</span>
    </span>
  </button>
</template>
