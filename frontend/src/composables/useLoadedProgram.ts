// Which G-code program LinuxCNC has loaded — one rule for every list
// that highlights it (G-code files, the dashboard's active-print widget).
//
// LinuxCNC reports the loaded file as an absolute path; lists know paths
// relative to nc_files/ (``project/part.ngc``). With folders, base names
// are not unique, so `loadedPathAmong` picks the longest relative path
// the absolute one ends with (``/…/nc_files/project/a.ngc`` is
// ``project/a.ngc``, not the top-level ``a.ngc``). Nothing counts as
// loaded while the machine is idle (no program open).

import { computed } from "vue";
import { storeToRefs } from "pinia";

import { SystemState, useMachineStore } from "../stores/stateFacade";

/** `"/home/cnc/nc_files/part.ngc"` → `"part.ngc"` (either slash). */
export function programBaseName(path: string | null | undefined): string {
  if (typeof path !== "string") return "";
  return path.split("/").pop()?.split("\\").pop() ?? "";
}

/** Of `relativePaths`, the one `loadedFile` (absolute) points at — the
 *  longest that `loadedFile` ends with at a folder boundary; `null` if none. */
export function matchLoadedPath(loadedFile: string | null | undefined, relativePaths: readonly string[]): string | null {
  if (!loadedFile) return null;
  const loaded = loadedFile.replace(/\\/g, "/");
  let best: string | null = null;
  for (const path of relativePaths) {
    if ((loaded === path || loaded.endsWith(`/${path}`)) && (best === null || path.length > best.length)) best = path;
  }
  return best;
}

/** The program's path relative to nc_files/ (what the files API takes):
 *  the part after the last ``/nc_files/``, else the base name. */
export function programRelativePath(path: string | null | undefined): string {
  if (typeof path !== "string") return "";
  const normalized = path.replace(/\\/g, "/");
  const marker = normalized.lastIndexOf("/nc_files/");
  return marker >= 0 ? normalized.slice(marker + "/nc_files/".length) : programBaseName(normalized);
}

export function useLoadedProgram() {
  const { systemState, status } = storeToRefs(useMachineStore());

  /** Base name of the loaded program, or `null` when none is loaded. */
  const loadedName = computed<string | null>(() => {
    if (systemState.value === SystemState.IDLE) return null;
    return programBaseName(status.value?.file) || null;
  });

  function isLoadedFile(filename: string | null | undefined): boolean {
    return loadedName.value !== null && !!filename && programBaseName(filename) === loadedName.value;
  }

  /** The loaded program among `relativePaths` (see `matchLoadedPath`). */
  function loadedPathAmong(relativePaths: readonly string[]): string | null {
    if (systemState.value === SystemState.IDLE) return null;
    return matchLoadedPath(status.value?.file, relativePaths);
  }

  /** The loaded program relative to nc_files/, or `null` when none is loaded. */
  const loadedRelativePath = computed<string | null>(() => {
    if (systemState.value === SystemState.IDLE) return null;
    return programRelativePath(status.value?.file) || null;
  });

  return { loadedName, loadedRelativePath, isLoadedFile, loadedPathAmong };
}
