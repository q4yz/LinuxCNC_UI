// The Calibration tab's badge: reminders due. The view sets it whenever it
// lists the calibrations; the sidebar also polls it (slowly) so the badge
// shows without opening the tab.
import { ref } from "vue";
import { calibrationFacade } from "../facades/calibrationFacade";

const due = ref(0);
let polling: ReturnType<typeof setInterval> | null = null;

async function poll() {
  try {
    due.value = (await calibrationFacade.list()).due ?? 0;
  } catch {
    /* machine backend down: keep the last count */
  }
}

export function useCalibrationDue() {
  return {
    due,
    setDue: (n: number) => (due.value = n),
    startPolling: (ms = 300_000) => {
      if (polling) return;
      poll();
      polling = setInterval(poll, ms);
    },
  };
}
