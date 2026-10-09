<script setup lang="ts">
// Shared file selector: drag & drop onto the wrapped content plus a
// hidden <input type="file"> the slot opens via ``openPicker``. Every
// file selector in the app (G-code files, profiles, machines) uses
// this, so selection always allows several files at once.
//
// Drag tracking counts dragenter/dragleave pairs: moving across child
// elements fires a leave for the parent, and a plain boolean would
// flicker the overlay (the old MachinesExplorer bug). Drags without
// files (text, a row being dragged) are ignored.
import { ref } from "vue";

const props = withDefaults(
  defineProps<{
    /** Where the files go — shown in the overlay ("Drop files into …"). */
    target: string;
    /** Same syntax as the input's ``accept`` (".ngc,.gcode,text/plain"). */
    accept?: string;
    multiple?: boolean;
    disabled?: boolean;
  }>(),
  { accept: "", multiple: true, disabled: false },
);

const emit = defineEmits<{
  /** The selected / dropped files that match ``accept`` (never empty). */
  (e: "files", files: File[]): void;
  /** Dropped files that do not match ``accept`` (never empty). */
  (e: "rejected", files: File[]): void;
}>();

const input = ref<HTMLInputElement | null>(null);
const isDragging = ref(false);
let dragDepth = 0;

function carriesFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

function matchesAccept(file: File): boolean {
  const rules = props.accept.split(",").map((r) => r.trim().toLowerCase()).filter(Boolean);
  if (!rules.length) return true;
  const name = file.name.toLowerCase();
  const type = (file.type || "").toLowerCase();
  return rules.some((rule) => {
    if (rule.startsWith(".")) return name.endsWith(rule);
    if (rule.endsWith("/*")) return type.startsWith(rule.slice(0, -1));
    return type === rule;
  });
}

function deliver(files: File[]): void {
  const picked = props.multiple ? files : files.slice(0, 1);
  const accepted = picked.filter(matchesAccept);
  const rejected = picked.filter((file) => !matchesAccept(file));
  if (rejected.length) emit("rejected", rejected);
  if (accepted.length) emit("files", accepted);
}

function onDragEnter(event: DragEvent): void {
  if (props.disabled || !carriesFiles(event)) return;
  event.preventDefault();
  dragDepth++;
  isDragging.value = true;
}

function onDragOver(event: DragEvent): void {
  if (props.disabled || !carriesFiles(event)) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
}

function onDragLeave(event: DragEvent): void {
  if (props.disabled || !carriesFiles(event)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) isDragging.value = false;
}

function onDrop(event: DragEvent): void {
  if (props.disabled || !carriesFiles(event)) return;
  event.preventDefault();
  dragDepth = 0;
  isDragging.value = false;
  deliver(Array.from(event.dataTransfer?.files ?? []));
}

function openPicker(): void {
  if (!props.disabled) input.value?.click();
}

function onPicked(event: Event): void {
  const el = event.target as HTMLInputElement;
  deliver(Array.from(el.files ?? []));
  // Reset so picking the same file again still fires ``change``.
  el.value = "";
}

defineExpose({ openPicker });
</script>

<template>
  <div
    class="relative"
    data-test="file-drop-zone"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="input"
      type="file"
      class="hidden"
      :accept="accept || undefined"
      :multiple="multiple"
      data-test="file-drop-zone-input"
      @change="onPicked"
    />
    <slot :open-picker="openPicker" :is-dragging="isDragging" />
    <div
      v-if="isDragging"
      class="pointer-events-none absolute inset-2 z-20 flex flex-col items-center justify-center gap-1 rounded border-2 border-dashed border-blue-400 bg-gray-950/80 text-center font-semibold text-blue-200"
      data-test="file-drop-zone-overlay"
    >
      <span>Drop {{ multiple ? 'files' : 'a file' }} into {{ target }}</span>
      <span v-if="accept" class="text-xs font-normal text-blue-300/80">{{ accept }}</span>
    </div>
  </div>
</template>
