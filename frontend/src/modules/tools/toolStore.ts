import {ToolsService} from "../../facades/toolsFacade";
import {useConsoleStore} from "../../stores/console";
import {Extruder} from "../../entities/tools";
import {ExtruderControlRequest} from "../../entities/tools/Extruder";
import {SpindleDigitalControlRequest} from "../../entities/tools/SpindleDigital";
import {HeaterControlRequest} from "../../entities/tools/Heater";
import {computed, onScopeDispose, ref, watch} from "vue";
import {defineStore, storeToRefs} from "pinia";
import {manifest} from "./index";
import useBaseThreadStore from "../../stores/baseThread";

const STORE_ID = `module_${manifest.id}`;

export const useToolStore = defineStore(STORE_ID, () => {
  // --- selection state (store-owned) ------------------------------ //
  const selectedToolId = ref<string | null>(null);

  // --- base-thread consumer -------------------------------------- //
  const baseThread = useBaseThreadStore();

  // Expose legacy `tools` for the migration window, but use 
  // the typed `toolList` for all new logic.
  const { tools, toolList } = storeToRefs(baseThread);

  const selectedTool = computed(() => {
    if (!selectedToolId.value || !toolList.value) return null;
    return toolList.value.get(selectedToolId.value) || null;
  });

  function setSelectedToolId(id: string) {
    selectedToolId.value = id;
  }

  async function refreshTools() {
    await baseThread.refresh();
  }

  // --- actions (all via ToolsService) ------------------------------ //

  /**
   * Send a spindle command.
   * (Signature kept flat to prevent breaking legacy UI components)
   */
  async function sendSpindleCommand(
      toolId: string,
      action: "forward" | "backward" | "stop",
      speed: number,
      masterOverride = 0,
      masterOverrideEnable = false,
      override = 1.0,
  ) {
    const request: SpindleDigitalControlRequest = {
      toolId,
      action,
      speed,
      masterOverride,
      masterOverrideEnable,
      override,
    };

    const result = await ToolsService.controlSpindle(request);

    if (!result.success) {
      useConsoleStore().error(`Spindle command failed: ${result.message}`);
    }
    return result;
  }

  /**
   * Send an extrude / retract command. Reads the current target
   * off the strictly typed snapshot to avoid an extra round-trip.
   */
  async function sendExtruderCommand(
      toolId: string,
      action: "extrude" | "retract",
      distance: number,
      speed: number
  ) {
    const tool = toolList.value?.get(toolId);

    // Safely extract the target using our domain classes! No more guessing wire shapes.
    const currentTarget: number = (tool instanceof Extruder && tool.heater)
        ? tool.heater.targetCelsius
        : 0;

    const heaterAction = currentTarget > 0 ? "set" : "noop";

    const request: ExtruderControlRequest = {
      toolId,
      action,
      distance,
      speed,
      heater: new HeaterControlRequest({toolId : toolId, target : currentTarget}),
      heaterAction,
    };

    const result = await ToolsService.controlExtruder(request);

    if (!result.success) {
      useConsoleStore().error(`Extruder command failed: ${result.message}`);
    } else {
      useConsoleStore().info(`${action} ${distance}mm at ${speed}mm/min`);
    }
    return result;
  }

  /**
   * Set the target temperature for a heating tool.
   */
  async function sendToolTarget(toolId: string, target: number) {
    const request: HeaterControlRequest = new HeaterControlRequest( {toolId, target} );
    const result = await ToolsService.setTarget(request);

    if (!result.success) {
      useConsoleStore().error(`Tool target failed: ${result.message}`);
    }
    return result;
  }

  // Auto-pick the first tool when none is selected.
  // Watching `ids()` is much faster and safer than deep-watching an array of objects.
  const stopToolsWatch = watch(
      () => toolList.value?.ids(),
      (ids) => {
        if (!selectedToolId.value && ids && ids.length > 0) {
          selectedToolId.value = ids[0];
        }
      },
      { immediate: true }
  );

  onScopeDispose(() => {
    stopToolsWatch();
  });

  // Public surface.
  return {
    tools,
    toolList,
    selectedToolId,
    selectedTool,
    setSelectedToolId,
    refreshTools,
    sendSpindleCommand,
    sendExtruderCommand,
    sendToolTarget,
  };
});

/**
 * Convenience wrapper around `storeToRefs` so callers can
 * destructure the reactive state without losing reactivity.
 */
export function useToolRefs() {
  const store = useToolStore();
  return { store, ...storeToRefs(store) };
}

export default useToolStore;