<script setup>
// Shared "custom macro button" primitive.
//
// Renders an operator-configurable button anywhere a UI surface wants
// to expose a one-click macro dispatch. The host component looks up
// the resolved config for its ``slot`` id (via the
// ``useMacroButtonConfig`` composable) and passes it down; the
// component itself is fully presentational and knows nothing about
// how the config was persisted.
//
// Visibility contract:
//
//   * ``descriptor == null``           → render nothing.
//   * ``descriptor.enabled === false`` → render nothing.
//   * ``descriptor.macroName === ""``  → render nothing.
//
// That last rule lets the operator keep an enabled-but-unfilled row
// in the settings editor without a phantom button appearing in the
// host surface. The settings editor shows a helper hint to that
// effect.
//
// Dispatch path:
//
//   * ``macroKind === "macro"`` → ``useMacrosStore().runMacro``
//     (the existing MDI block-dispatch path — parses .macro bodies
//     into static / python blocks, fires each static line via MDI,
//     honours the E-Stop guard).
//   * ``macroKind === "ngc"``   → ``useMacrosStore().runMacroOfKind("ngc", name)``,
//     which routes through the generated client's ``startMacro`` so
//     the backend's ``POST /api/v1/modules/macros/{name}/start?kind=ngc``
//     switches the controller to MDI mode and runs the NGC
//     subroutine. ``.mcode`` is intentionally excluded from the
//     selector: an operator who needs an mcode can wrap it in a
//     ``.macro`` (see ``.agent/contracts/frontend-module.md`` for
//     the kind taxonomy).
//
// Icon rendering:
//
//   * ``icon`` matching one of the names in ``<Icon>`` → renders
//     via the shared primitive, so a future icon-set change
//     propagates automatically.
//   * Anything else (emoji, plain text) → renders verbatim in a
//     ``<span>`` so the operator can drop ``💡`` / ``🔦`` / ``▶``
//     without us maintaining a separate emoji dictionary.
//
// Disabled while:
//
//   * the machine is in E-Stop (the macros store also blocks
//     dispatch, but disabling here keeps the button visually
//     muted).
//   * another macro is already running (``isBusy``).
//
// The button is non-functional while loading and shows the shared
// ``<Button>`` spinner so the operator sees the in-flight state.

import { computed, ref } from "vue";

import Button from "./Button.vue";
import Icon from "./Icon.vue";
import { useMacrosStore, MACRO_KIND } from "../modules/macros/store";
import { useMachineStore } from "../stores/machine";

const props = defineProps({
  // Resolved config row from ``useMacroButtonConfig``. ``null``
  // renders nothing — the host decides which slot id feeds in.
  descriptor: {
    type: Object,
    default: null,
    // Allow ``null`` so a missing config keeps the host surface
    // clean without prop-validation noise.
    validator: (v) =>
      v === null ||
      (typeof v === "object" &&
        typeof v.slot === "string" &&
        typeof v.enabled === "boolean" &&
        typeof v.name === "string" &&
        typeof v.icon === "string" &&
        typeof v.macroName === "string" &&
        (v.macroKind === MACRO_KIND.MACRO || v.macroKind === MACRO_KIND.NGC)),
  },
  // Visual variants — matches the ``<Button>`` primitive so a
  // host can request the same look-and-feel as its sibling
  // buttons.
  variant: {
    type: String,
    default: "primary",
    validator: (v) =>
      ["primary", "success", "danger", "secondary", "ghost"].includes(v),
  },
  // Sizes — ``sm`` matches the existing home/set buttons in the
  // DRO row so the new macro button lands inline without a layout
  // shift.
  size: {
    type: String,
    default: "sm",
    validator: (s) => ["sm", "md", "lg"].includes(s),
  },
  // Tooltip override. Defaults to the descriptor's ``name`` so a
  // button rendered as an icon still announces itself on hover.
  title: { type: String, default: "" },
  // Tailwind passthrough for one-off positioning tweaks.
  class: { type: String, default: "" },
});

const macrosStore = useMacrosStore();
const machineStore = useMachineStore();

// Local in-flight flag — flipped while ``runMacroOfKind`` is
// awaiting. The store's ``isBusy`` is global (any macro), so the
// local flag gives the user per-button feedback.
const isRunning = ref(false);

const isVisible = computed(
  () =>
    props.descriptor !== null &&
    props.descriptor.enabled === true &&
    props.descriptor.macroName.length > 0,
);

const isDisabled = computed(
  () =>
    !isVisible.value ||
    isRunning.value ||
    macrosStore.isBusy ||
    machineStore.isEstopActive,
);

// ``Icon`` knows the same set as ``<Icon name="...">``; a miss
// renders an empty SVG placeholder. We treat the icon as raw text
// when it doesn't match any known name so emoji / unicode glyphs
// still render. The check is a small allowlist: same names the
// primitive exposes — nothing more.
const KNOWN_ICONS = new Set([
  "close",
  "edit",
  "delete",
  "save",
  "refresh",
  "plus",
  "alert",
  "info",
  "check",
  "chevronDown",
  "chevronLeft",
  "warning",
  "plusCircle",
]);

const iconIsKnown = computed(
  () =>
    props.descriptor !== null &&
    KNOWN_ICONS.has(props.descriptor.icon),
);

const resolvedTitle = computed(() => {
  if (props.title) return props.title;
  if (props.descriptor && props.descriptor.name) return props.descriptor.name;
  return "";
});

async function onClick() {
  if (!props.descriptor) return;
  if (isDisabled.value) return;
  isRunning.value = true;
  try {
    await macrosStore.runMacroOfKind(
      props.descriptor.macroKind,
      props.descriptor.macroName,
    );
  } finally {
    isRunning.value = false;
  }
}
</script>

<template>
  <Button
    v-if="isVisible"
    :variant="variant"
    :size="size"
    :disabled="isDisabled"
    :loading="isRunning"
    :title="resolvedTitle"
    :class="class"
    @click="onClick"
  >
    <Icon
      v-if="iconIsKnown"
      :name="descriptor.icon"
      :size="size === 'sm' ? 'h-4 w-4' : size === 'lg' ? 'h-6 w-6' : 'h-5 w-5'"
    />
    <span v-else-if="descriptor.icon">{{ descriptor.icon }}</span>
    <span>{{ descriptor.name }}</span>
  </Button>
</template>