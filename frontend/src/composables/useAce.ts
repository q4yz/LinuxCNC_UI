// The ACE Pro's state for every card that shows it: polled every second
// while at least one is mounted (a tool change moves through its steps
// quickly), one shared state. Actions report failures to the console.
import { onBeforeUnmount, onMounted, ref } from "vue";

import { describeErrorOr } from "../core/error-format";
import { aceFacade, type AceState } from "../facades/aceFacade";
import { useConsoleStore } from "../stores/console";

const POLL_MS = 1000;

const state = ref<AceState | null>(null);
const busy = ref(false);
let users = 0;
let timer: ReturnType<typeof setInterval> | null = null;

async function refresh(): Promise<void> {
  try {
    state.value = await aceFacade.get();
  } catch {
    // backend unreachable: keep the last state, the next poll tries again
  }
}

async function run(what: string, action: () => Promise<AceState>): Promise<boolean> {
  busy.value = true;
  try {
    state.value = await action();
    return true;
  } catch (error) {
    useConsoleStore().error(`ACE ${what}: ${describeErrorOr(error)}`, { popup: true });
    return false;
  } finally {
    busy.value = false;
  }
}

export function useAce() {
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
    refresh,
    load: (slot: number) => run(`load T${slot}`, () => aceFacade.change(slot)),
    unload: () => run("unload", () => aceFacade.change(-1)),
    feed: (index: number, length: number, speed: number) =>
      run(`feed T${index}`, () => aceFacade.feed(index, length, speed)),
    unwind: (index: number, length: number, speed: number) =>
      run(`wind back T${index}`, () => aceFacade.unwind(index, length, speed)),
    startDrying: (temp: number, minutes: number) => run("drying", () => aceFacade.startDrying(temp, minutes)),
    stopDrying: () => run("stop drying", () => aceFacade.stopDrying()),
    setCurrent: (slot: number) => run("set the loaded slot", () => aceFacade.setCurrent(slot)),
  };
}
