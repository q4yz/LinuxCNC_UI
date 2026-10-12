<script setup lang="ts">
// "⋮" actions menu for a list row. The dropdown is teleported to <body>
// with fixed positioning, so a scrolling list never clips it; it opens
// upwards when there is no room below. Closes on outside click, Escape,
// scroll and resize. Emits `select` with the chosen item's key.

import { nextTick, onBeforeUnmount, ref } from "vue";

export interface ActionMenuItem {
  key: string;
  label: string;
  /** Red text (destructive). */
  danger?: boolean;
  disabled?: boolean;
  /** Thin separator above this item. */
  separated?: boolean;
}

const props = withDefaults(
  defineProps<{ items: ActionMenuItem[]; label?: string; testId?: string }>(),
  { label: "More actions", testId: "" },
);
const emit = defineEmits<{ select: [key: string] }>();

const open = ref(false);
const button = ref<HTMLButtonElement | null>(null);
const menu = ref<HTMLElement | null>(null);
const position = ref<{ top: number; right: number }>({ top: 0, right: 0 });

function place(): void {
  const rect = button.value?.getBoundingClientRect();
  if (!rect) return;
  const height = menu.value?.offsetHeight ?? 0;
  const below = rect.bottom + 4;
  const top = below + height > window.innerHeight - 8 ? Math.max(8, rect.top - 4 - height) : below;
  position.value = { top, right: Math.max(8, window.innerWidth - rect.right) };
}

function onOutside(event: PointerEvent): void {
  const target = event.target as Node | null;
  if (target && (menu.value?.contains(target) || button.value?.contains(target))) return;
  close();
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape") close();
}

function listen(on: boolean): void {
  const method = on ? "addEventListener" : "removeEventListener";
  document[method]("pointerdown", onOutside as EventListener, true);
  document[method]("keydown", onKey as EventListener);
  window[method]("scroll", close, true);
  window[method]("resize", close);
}

async function toggle(): Promise<void> {
  if (open.value) {
    close();
    return;
  }
  open.value = true;
  listen(true);
  await nextTick();
  place();
}

function close(): void {
  if (!open.value) return;
  open.value = false;
  listen(false);
}

function choose(item: ActionMenuItem): void {
  if (item.disabled) return;
  close();
  emit("select", item.key);
}

onBeforeUnmount(() => listen(false));
</script>

<template>
  <button
    ref="button"
    type="button"
    class="rounded px-2 py-1 text-gray-400 hover:bg-gray-700 hover:text-gray-100"
    :title="props.label"
    :aria-label="props.label"
    aria-haspopup="menu"
    :aria-expanded="open"
    :data-test="testId ? `${testId}-menu` : undefined"
    @click.stop="toggle"
  >⋮</button>
  <Teleport to="body">
    <div
      v-if="open"
      ref="menu"
      role="menu"
      class="fixed z-50 min-w-[11rem] rounded border border-gray-600 bg-gray-900 py-1 text-sm"
      :style="{ top: `${position.top}px`, right: `${position.right}px` }"
      :data-test="testId ? `${testId}-items` : undefined"
      @click.stop
    >
      <template v-for="item in items" :key="item.key">
        <div v-if="item.separated" class="my-1 border-t border-gray-700" role="separator" />
        <button
          type="button"
          role="menuitem"
          class="block w-full px-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-40"
          :class="item.danger ? 'text-red-300 hover:bg-red-900/40' : 'text-gray-200 hover:bg-gray-700'"
          :disabled="item.disabled"
          :data-test="testId ? `${testId}-${item.key}` : undefined"
          @click="choose(item)"
        >
          {{ item.label }}
        </button>
      </template>
    </div>
  </Teleport>
</template>
