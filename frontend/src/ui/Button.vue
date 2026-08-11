<script setup>
// Shared button primitive.
//
// Consolidates the four button classes that appear across the
// dashboard today (e.g. ``bg-blue-600 hover:bg-blue-500`` for
// confirm, ``bg-red-600 hover:bg-red-500`` for delete,
// ``bg-green-600`` for run / save, ``border border-gray-600`` for
// cancel). Each call site used to repeat the Tailwind classes;
// this component moves that into one place so a future palette
// change touches a single file.
//
// Variants:
//   ``primary`` — blue, used for confirm / save / load actions.
//   ``success`` — green, used for run / start.
//   ``danger``  — red, used for delete / stop / unload.
//   ``secondary`` — outlined, used for cancel.
//   ``ghost``   — transparent, used for in-row actions.
//
// Sizes:
//   ``sm`` — toolbar / inline actions.
//   ``md`` — default modal / panel actions.
//   ``lg`` — primary CTA (e.g. dashboard Start).
//
// ``loading`` swaps the disabled state for a spinner so the
// operator sees in-flight work. ``icon`` slot renders before the
// default slot when present so the existing "+ New macro",
// "✕", "↻ Refresh" patterns render with the icon on the left.

import { computed } from "vue";

const props = defineProps({
  // Visual variants.
  variant: {
    type: String,
    default: "primary",
    validator: (v) =>
      ["primary", "success", "danger", "secondary", "ghost"].includes(v),
  },
  // Sizes.
  size: {
    type: String,
    default: "md",
    validator: (s) => ["sm", "md", "lg"].includes(s),
  },
  // Disabled state. Forwarded to the underlying button so it wins
  // over a caller-supplied ``disabled`` attribute.
  disabled: { type: Boolean, default: false },
  // Spinner state. ``disabled`` is automatically implied so the
  // button cannot fire while the call is in flight.
  loading: { type: Boolean, default: false },
  // Native button type. Defaults to ``button`` so a stray use
  // inside a form does not accidentally submit.
  type: { type: String, default: "button" },
  // Tailwind class passthrough for one-off spacing tweaks. Kept
  // narrow on purpose; the library should not become a dumping
  // ground for arbitrary Tailwind.
  class: { type: String, default: "" },
});

const VARIANT_CLASSES = {
  primary: "bg-blue-600 hover:bg-blue-500 text-white border-blue-600",
  success: "bg-green-600 hover:bg-green-500 text-white border-green-600",
  danger: "bg-red-600 hover:bg-red-500 text-white border-red-600",
  secondary:
    "border border-gray-600 bg-gray-700 hover:bg-gray-600 text-gray-100",
  ghost: "bg-transparent hover:bg-gray-700 text-gray-200 border-transparent",
};

const SIZE_CLASSES = {
  sm: "px-2 py-1 text-xs",
  md: "px-3 py-1.5 text-sm",
  lg: "px-4 py-3 text-base",
};

const baseClasses = computed(() => {
  const variant = VARIANT_CLASSES[props.variant] || VARIANT_CLASSES.primary;
  const size = SIZE_CLASSES[props.size] || SIZE_CLASSES.md;
  // Disabled + loading force the same muted treatment; loading is
  // an ``or-disabled`` because every loading button should also
  // be unclickable.
  const stateClasses =
    props.disabled || props.loading
      ? "opacity-50 cursor-not-allowed"
      : "cursor-pointer";
  // Common typography + shape. ``rounded-md`` is the canonical
  // radius across the rest of the dashboard; ``font-semibold``
  // matches the existing buttons on the machine widget.
  return [
    "inline-flex items-center justify-center gap-2",
    "rounded-md border font-semibold transition-colors",
    "focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-900",
    variant,
    size,
    stateClasses,
    props.class,
  ];
});
</script>

<template>
  <button
    :type="type"
    :class="baseClasses"
    :disabled="disabled || loading"
    :aria-busy="loading ? 'true' : 'false'"
  >
    <span
      v-if="loading"
      aria-hidden="true"
      class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
    ></span>
    <slot name="icon" />
    <slot />
  </button>
</template>
