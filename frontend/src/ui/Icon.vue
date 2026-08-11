<script setup>
// Shared inline SVG icon primitive.
//
// Replaces the dozens of ad-hoc ``<svg>...</svg>`` blocks scattered
// across the codebase today — see e.g. ``AppSidebar.vue:28-30`` (three
// icons duplicated), ``modules/camera/manifest.js:20-24`` (camera
// glyph), ``modules/machineconfig/manifest.js:14`` (gear glyph),
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
  close: {
    label: "Close",
    path:
      "M6 18 18 6M6 6l12 12",
    stroke: true,
  },
  edit: {
    label: "Edit",
    path:
      "M16.862 4.487 18.549 2.799a2.121 2.121 0 1 1 3 3L19.312 6.174a2.121 2.121 0 0 1-3 3L8.42 17.064a2 2 0 0 1-.879.51l-3.36 1.123a.5.5 0 0 1-.65-.65l1.123-3.36a2 2 0 0 1 .51-.879L16.862 4.487Zm-3.05 3.05L6.182 15.06l-1.123 3.36.65.65 3.36-1.123L21.78 7.59a3.121 3.121 0 0 0-4.41-4.41l-3.55 3.55Z",
    stroke: false,
  },
  delete: {
    label: "Delete",
    path:
      "M5.5 5.5A.5.5 0 0 1 6 5h4a.5.5 0 0 1 .5.5v.5h3v-.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .5.5v.5H19a.5.5 0 0 1 0 1h-1.056l-.76 11.34A2 2 0 0 1 15.19 20H8.81a2 2 0 0 1-1.994-1.66L6.056 6H5a.5.5 0 0 1-.5-.5Zm3.493 2.04.16 11.43a.5.5 0 0 0 .553.492l1.713-.36.16-1.132a.5.5 0 0 0-.553-.492l-1.713.36a.5.5 0 0 1-.553-.492Zm4.014 0 .16 11.43a.5.5 0 0 1-.553.492l-1.713-.36.16-1.132a.5.5 0 0 1 .553-.492l1.713.36a.5.5 0 0 0 .553-.492Z",
    stroke: false,
  },
  save: {
    label: "Save",
    path:
      "M17.593 3.322c1.1.128 1.907 1.477 2.407 1.977.5.5.85 1.357.926 2.413l.074 2.788H4.5l.074-2.788c.077-1.056.426-1.913.926-2.413.5-.5 1.307-.85 2.407-.977L8.5 2H15.5l1.493.322ZM5.5 10h13v8a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-8Zm3 2v5h7v-5h-7Z",
    stroke: false,
  },
  refresh: {
    label: "Refresh",
    path:
      "M17.65 6.35A7.96 7.96 0 0 0 12 4a7.95 7.95 0 0 0-6.69 3.34l-1.97-1.97V10h6.62l-1.96-1.96A5.97 5.97 0 0 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35ZM12 18a5.97 5.97 0 0 1-4.22-1.78L11 14H4v7l2.35-2.35A7.96 7.96 0 0 0 12 20a7.95 7.95 0 0 0 6.69-3.34l1.97 1.97V13h-6.62l1.96 1.96A5.97 5.97 0 0 1 12 18Z",
    stroke: false,
  },
  plus: {
    label: "Add",
    path:
      "M12 5a1 1 0 0 1 1 1v5h5a1 1 0 1 1 0 2h-5v5a1 1 0 1 1-2 0v-5H6a1 1 0 1 1 0-2h5V6a1 1 0 0 1 1-1Z",
    stroke: false,
  },
  alert: {
    label: "Alert",
    path:
      "M10 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm-.75-5.5a1.25 1.25 0 0 0 2.5 0V8.5a1.25 1.25 0 0 0-2.5 0V12.5ZM10 14.5a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z",
    stroke: false,
  },
  info: {
    label: "Info",
    path:
      "M10 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm.93-9.412-1.477.332a.5.5 0 0 0-.126.918l.378.21a.75.75 0 0 1-.36 1.4l-.27-.076a1 1 0 0 0-.79.434l-.706 1.205a.5.5 0 0 0 .806.56l.706-1.205a.5.5 0 0 1 .79-.434l.27.075a1.25 1.25 0 0 0 .602-2.41l-.378-.21a1 1 0 0 1 .13-1.86Zm1.07 5.412a1 1 0 1 0-1 1 1 1 0 0 0 1-1Z",
    stroke: false,
  },
  check: {
    label: "Check",
    path:
      "M16.704 5.29a1 1 0 0 1 .006 1.414l-7.7 7.7a1 1 0 0 1-1.42 0L3.286 9.9a1 1 0 0 1 1.428-1.4l4.59 4.59 6.99-6.99a1 1 0 0 1 1.41-.01Z",
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
    path:
      "M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495ZM10 6a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 6Zm0 9a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z",
    stroke: false,
  },
  plusCircle: {
    label: "Add",
    path:
      "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 11h4a1 1 0 1 1 0 2h-4v4a1 1 0 1 1-2 0v-4H7a1 1 0 1 1 0-2h4V7a1 1 0 1 1 2 0v4Z",
    stroke: false,
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

const icon = computed(() => ICONS[props.name] || null);

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
    :aria-hidden="label ? null : 'true'"
    :aria-label="label ? icon.label : null"
    :role="label ? 'img' : null"
    viewBox="0 0 24 24"
    fill="none"
    v-bind="attrs"
    data-test="icon"
    :data-icon="name"
  >
    <path
      :d="icon.path"
      :stroke="icon.stroke ? 'currentColor' : null"
      :stroke-width="icon.stroke ? 1.5 : null"
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
