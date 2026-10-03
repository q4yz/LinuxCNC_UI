// Logging for the settings core. Settings are created at import time —
// possibly before Pinia exists — so the console store is resolved per
// call (never at module scope, see LESSONS_LEARNED § cross-store imports)
// and falls back to the browser console when no Pinia is active yet.

import { getActivePinia } from "pinia";
import { useConsoleStore } from "../../stores/console";

type Level = "debug" | "info" | "success" | "warning" | "error";

const BROWSER: Record<Level, (msg: string) => void> = {
  debug: (m) => console.debug(m),
  info: (m) => console.info(m),
  success: (m) => console.info(m),
  warning: (m) => console.warn(m),
  error: (m) => console.error(m),
};

export function settingsLog(level: Level, message: string, popup = false): void {
  if (!getActivePinia()) {
    BROWSER[level](message);
    return;
  }
  const consoleStore = useConsoleStore();
  if (level === "debug") consoleStore.debug(message);
  else consoleStore[level](message, popup ? { popup: true } : undefined);
}
