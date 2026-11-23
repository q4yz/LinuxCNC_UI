// Live print tuning (``/api/v1/print-tuning``): the Z offset
// (babystepping), flow (M221), pressure advance, excluded objects and the
// slicer's progress (M73). One shared state for every component that
// shows a part of it (the Tuning card's controls, the Programs card's
// objects / slicer time): polled every 2 s while at least one of them is
// mounted.
import { onBeforeUnmount, onMounted, ref } from "vue";

import { describeErrorOr } from "../core/error-format";
import { printTuningFacade, type PrintTuningState } from "../facades/printTuningFacade";
import { useConsoleStore } from "../stores/console";

const POLL_MS = 2000;

const state = ref<PrintTuningState | null>(null);
const busy = ref(false);
let users = 0;
let timer: ReturnType<typeof setInterval> | null = null;

async function refresh(): Promise<void> {
  try {
    state.value = await printTuningFacade.get();
  } catch {
    // the last state stays; the next poll tries again
  }
}

async function run(what: string, action: () => Promise<PrintTuningState>): Promise<void> {
  busy.value = true;
  try {
    state.value = await action();
  } catch (error) {
    useConsoleStore().error(`${what}: ${describeErrorOr(error)}`);
  } finally {
    busy.value = false;
  }
}

export function usePrintTuning() {
  onMounted(() => {
    users += 1;
    if (users === 1) {
      void refresh();
      timer = setInterval(() => void refresh(), POLL_MS);
    }
  });
  onBeforeUnmount(() => {
    users -= 1;
    if (users === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  });

  return {
    state,
    busy,
    adjustZ: (delta: number) => run("Z offset", () => printTuningFacade.adjustZ(delta)),
    resetZ: () => run("Z offset", () => printTuningFacade.setZ(0)),
    setFlow: (percent: number) => run("Flow", () => printTuningFacade.setFlow(percent)),
    setPressureAdvance: (k: number) => run("Pressure advance", () => printTuningFacade.setPressureAdvance(k)),
    exclude: (index: number, excluded: boolean) => run("Exclude object", () => printTuningFacade.exclude(index, excluded)),
  };
}
