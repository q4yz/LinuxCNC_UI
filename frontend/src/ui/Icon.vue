<script setup lang="ts">
// Shared inline SVG icon primitive.
//
// Replaces the dozens of ad-hoc ``<svg>...</svg>`` blocks scattered
// across the codebase today — see e.g. ``AppSidebar.vue:28-30`` (three
// icons duplicated), ``AppSidebar.vue:34-40`` (camera + gear glyphs),
// ``EStopHeader.vue:62-66`` (chevron + hamburger), and the toolbar
// icons inside ``ActivePrintWidget.vue``. Each used the same Heroicons
// path data with subtly different class soup.
//
// The icon set is the small set the operator actually sees today —
// anything we need later is one entry added here, not a scattered
// find-and-replace across half a dozen files.
//
// Each name maps to a single ``<path d="..."/>`` so the SVG output
// stays trivial — a single path per icon, no nested groups, no
// animations. Consumers can override ``class`` for one-off sizing /
// colour tweaks but the component still passes ``aria-hidden``
// through so screen readers don't trip on decoration.

import { computed } from "vue";

// SVG path data — Heroicons / Lucide-style outline geometry. Kept
// inline so a frontend build doesn't need a separate icon font or
// dependency. ``label`` doubles as a screen-reader-only fallback
// when the consumer wants the icon to convey meaning (rare — most
// usages are decorative next to a text label).
const ICONS = {
  // --- Core UI Icons ---
  close: {
    label: "Close",
    path: "M6 18 18 6M6 6l12 12",
    stroke: true,
  },


  trash: {
    label: "Delete",
    path: "M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0",
    stroke: true,
  },
  edit: {
    label: "Edit",
    path: "m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125",
    stroke: true,
  },


  delete: {
    label: "Delete",
    path: "M5.5 5.5A.5.5 0 0 1 6 5h4a.5.5 0 0 1 .5.5v.5h3v-.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .5.5v.5H19a.5.5 0 0 1 0 1h-1.056l-.76 11.34A2 2 0 0 1 15.19 20H8.81a2 2 0 0 1-1.994-1.66L6.056 6H5a.5.5 0 0 1-.5-.5Zm3.493 2.04.16 11.43a.5.5 0 0 0 .553.492l1.713-.36.16-1.132a.5.5 0 0 0-.553-.492l-1.713.36a.5.5 0 0 1-.553-.492Zm4.014 0 .16 11.43a.5.5 0 0 1-.553.492l-1.713-.36.16-1.132a.5.5 0 0 1 .553-.492l1.713.36a.5.5 0 0 0 .553-.492Z",
    stroke: false,
  },
  save: {
    label: "Save",
    path: "M17.593 3.322c1.1.128 1.907 1.477 2.407 1.977.5.5.85 1.357.926 2.413l.074 2.788H4.5l.074-2.788c.077-1.056.426-1.913.926-2.413.5-.5 1.307-.85 2.407-.977L8.5 2H15.5l1.493.322ZM5.5 10h13v8a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-8Zm3 2v5h7v-5h-7Z",
    stroke: false,
  },
  refresh: {
    label: "Refresh",
    path: "M17.65 6.35A7.96 7.96 0 0 0 12 4a7.95 7.95 0 0 0-6.69 3.34l-1.97-1.97V10h6.62l-1.96-1.96A5.97 5.97 0 0 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35ZM12 18a5.97 5.97 0 0 1-4.22-1.78L11 14H4v7l2.35-2.35A7.96 7.96 0 0 0 12 20a7.95 7.95 0 0 0 6.69-3.34l1.97 1.97V13h-6.62l1.96 1.96A5.97 5.97 0 0 1 12 18Z",
    stroke: false,
  },
  plus: {
    label: "Add",
    path: "M12 5a1 1 0 0 1 1 1v5h5a1 1 0 1 1 0 2h-5v5a1 1 0 1 1-2 0v-5H6a1 1 0 1 1 0-2h5V6a1 1 0 0 1 1-1Z",
    stroke: false,
  },
  alert: {
    label: "Alert",
    path: "M10 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm-.75-5.5a1.25 1.25 0 0 0 2.5 0V8.5a1.25 1.25 0 0 0-2.5 0V12.5ZM10 14.5a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z",
    stroke: false,
  },
  info: {
    label: "Info",
    path: "M10 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm.93-9.412-1.477.332a.5.5 0 0 0-.126.918l.378.21a.75.75 0 0 1-.36 1.4l-.27-.076a1 1 0 0 0-.79.434l-.706 1.205a.5.5 0 0 0 .806.56l.706-1.205a.5.5 0 0 1 .79-.434l.27.075a1.25 1.25 0 0 0 .602-2.41l-.378-.21a1 1 0 0 1 .13-1.86Zm1.07 5.412a1 1 0 1 0-1 1 1 1 0 0 0 1-1Z",
    stroke: false,
  },
  check: {
    label: "Check",
    path: "M16.704 5.29a1 1 0 0 1 .006 1.414l-7.7 7.7a1 1 0 0 1-1.42 0L3.286 9.9a1 1 0 0 1 1.428-1.4l4.59 4.59 6.99-6.99a1 1 0 0 1 1.41-.01Z",
    stroke: false,
  },
  chevronDown: {
    label: "Toggle",
    path: "M6 9l6 6 6-6",
    stroke: true,
  },
  chevronLeft: {
    label: "Back",
    path: "M15 18l-6-6 6-6",
    stroke: true,
  },
  warning: {
    label: "Warning",
    path: "M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495ZM10 6a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 6Zm0 9a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z",
    stroke: false,
  },
  plusCircle: {
    label: "Add",
    path: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 11h4a1 1 0 1 1 0 2h-4v4a1 1 0 1 1-2 0v-4H7a1 1 0 1 1 0-2h4V7a1 1 0 1 1 2 0v4Z",
    stroke: false,
  },

  // --- Content icons (replace colour emojis: Linux has no emoji font) ---
  home: {
    label: "Home",
    path: "m2.25 12 8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25",
    stroke: true,
  },
  folder: {
    label: "Folder",
    path: "M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z",
    stroke: true,
  },
  file: {
    label: "File",
    path: "M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z",
    stroke: true,
  },
  upload: {
    label: "Upload",
    path: "M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5",
    stroke: true,
  },
  download: {
    label: "Download",
    path: "M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3",
    stroke: true,
  },
  log: {
    label: "Log",
    path: "M8 7h8M8 11h8M8 15h5M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z",
    stroke: true,
  },
  stop: {
    label: "Stop",
    path: "M5.25 7.5A2.25 2.25 0 0 1 7.5 5.25h9a2.25 2.25 0 0 1 2.25 2.25v9a2.25 2.25 0 0 1-2.25 2.25h-9a2.25 2.25 0 0 1-2.25-2.25v-9Z",
    stroke: true,
  },
  macro: {
    label: "Macro",
    path: "m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z",
    stroke: true,
  },
  flame: {
    label: "Temperature",
    path: "M15.362 5.214A8.252 8.252 0 0 1 12 21 8.25 8.25 0 0 1 6.038 7.047 8.287 8.287 0 0 0 9 9.601a8.983 8.983 0 0 1 3.361-6.867 8.21 8.21 0 0 0 3 2.48Z M12 18a3.75 3.75 0 0 0 .495-7.468 5.99 5.99 0 0 0-1.925 3.547 5.975 5.975 0 0 1-2.133-1.001A3.75 3.75 0 0 0 12 18Z",
    stroke: true,
  },
  snowflake: {
    label: "Cool down",
    path: "M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9.5 4.5 12 7l2.5-2.5M9.5 19.5 12 17l2.5 2.5",
    stroke: true,
  },
  eye: {
    label: "Shown",
    path: "M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
    stroke: true,
  },
  eyeOff: {
    label: "Hidden",
    path: "M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88",
    stroke: true,
  },

  // --- Sidebar Menu Icons ---
  dashboard: {
    label: "Dashboard",
    path: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6",
    stroke: true,
  },
  programs: {
    label: "G-Code Files",
    path: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
    stroke: true,
  },
  camera: {
    label: "Camera",
    path: "M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z M15 13a3 3 0 11-6 0 3 3 0 016 0z",
    stroke: true,
  },
  config: {
    label: "Config",
    path: "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01",
    stroke: true,
  },
  settings: {
    label: "Settings",
    path: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z",
    stroke: true,
  },
  jogging: {
    label: "Jogging",
    path: "M12 4v16m0-16l-3 3m3-3l3 3m-3 13l-3-3m3 3l3-3M4 12h16m-16 0l3-3m-3 3l3 3m13-3l-3-3m3 3l-3 3",
    stroke: true,
  },
  running: {
    label: "Running",
    path: "M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
    stroke: true,
  },
  debug: {
    label: "Debug",
    path: "M9 9v-1a3 3 0 0 1 6 0v1 M8 9h8a6 6 0 0 1 1 3v3a5 5 0 0 1 -10 0v-3a6 6 0 0 1 1 -3 M3 13h4 M17 13h4 M12 20v-6 M4 19l3.35-2 M20 19l-3.35-2 M4 7l3.75 2.4 M20 7l-3.75 2.4",
    stroke: true,
  },
  probing: {
    label: "Probing",
    path: "M12 2v3 M12 19v3 M2 12h3 M19 12h3 M12 12m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0",
    stroke: true,
  },

};

const props = defineProps({
  // Required icon name. Falsy / unknown names render an empty
  // ``<svg>`` so a missing icon doesn't fall back to a default
  // that might mislead the operator.
  name: { type: String, required: true },
  // Tailwind size class. Defaults to ``h-4 w-4`` to match the
  // existing 16×16 icons in ``AppSidebar.vue``.
  size: { type: String, default: "h-4 w-4" },
  // Tailwind class passthrough for one-off colour tweaks.
  class: { type: String, default: "" },
  // When ``true``, expose the icon's label as ``aria-label`` so
  // screen readers announce it. The default (``false``) is
  // ``aria-hidden="true"`` because most icons sit next to a
  // visible text label.
  label: { type: Boolean, default: false },
});

const icon = computed(
  () => ICONS[props.name as keyof typeof ICONS] || null,
);

// Filled icons get ``fill="currentColor"`` so ``text-...`` Tailwind
// classes drive the colour. Outline icons get ``fill="none"`` and
// ``stroke="currentColor"`` with a 1.5-pixel stroke. Both share a
// 24×24 viewBox matching Heroicons.
const attrs = computed(() => {
  const meta = icon.value;
  if (!meta) return { fill: "none" };
  return meta.stroke
    ? { fill: "none", "stroke-width": "1.5", stroke: "currentColor" }
    : { fill: "currentColor" };
});
</script>

<template>
  <svg
    v-if="icon"
    :class="[size, 'shrink-0', props.class]"
    :aria-hidden="label ? undefined : 'true'"
    :aria-label="label ? icon.label : undefined"
    :role="label ? 'img' : undefined"
    viewBox="0 0 24 24"
    v-bind="attrs"
    data-test="icon"
    :data-icon="name"
  >
    <path
      :d="icon.path"
      :stroke="icon.stroke ? 'currentColor' : undefined"
      :stroke-width="icon.stroke ? 1.5 : undefined"
      :fill="icon.stroke ? 'none' : 'currentColor'"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
  <svg v-else :class="[size, 'shrink-0', props.class]" aria-hidden="true" viewBox="0 0 24 24" data-test="icon" :data-icon="name">
    <!-- Empty placeholder so layouts don't shift when an unknown
         icon name slips through. -->
  </svg>
</template>