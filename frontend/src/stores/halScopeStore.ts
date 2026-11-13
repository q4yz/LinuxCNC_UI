// HAL oscilloscope state (Debug -> HAL pins -> Oscilloscope): created once
// and kept for the session, so leaving the Debug view and coming back
// finds the same channels, per-channel V/div / shift / colour, sample
// rate, time/div, run state and trigger. Only the samples themselves
// (the stream's ScopeBuffer) start again on return.

import { defineStore } from "pinia";
import { reactive, ref } from "vue";

import type { TriggerEdge, TriggerMode } from "../components/debug/scope/scopeMath";

export interface ScopeChannelSettings {
  color: string;
  visible: boolean;
  /** Value units per division. */
  scale: number;
  /** Vertical shift in divisions (+ = up). */
  offset: number;
}

export interface ScopeTrigger {
  source: string;
  edge: TriggerEdge;
  mode: TriggerMode;
  level: number;
  position: number;
}

export const useHalScopeStore = defineStore("halScope", () => {
  /** The channels: HAL pin names, in order. */
  const pins = ref<string[]>([]);
  const settings = reactive<Record<string, ScopeChannelSettings>>({});
  const rateHz = ref(200);
  const timePerDiv = ref(0.2);
  const running = ref(true);
  const trigger = reactive<ScopeTrigger>({
    source: "",
    edge: "rising",
    mode: "auto",
    level: 0.5,
    position: 0.5,
  });
  /** Channels already auto-fitted (or set by hand): never fitted again. */
  const autoScaled = new Set<string>();

  return { pins, settings, rateHz, timePerDiv, running, trigger, autoScaled };
});
