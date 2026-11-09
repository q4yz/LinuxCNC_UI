// Drag & drop for the explorers (G-code files, Machines, Profiles): drag a
// row onto a folder (or a breadcrumb / "up" — out of the open folder) to
// move it, onto the bin (``DragBin``) to delete it. The caller supplies
// the move and the delete (with its own confirmation).

import { ref } from "vue";
import { ENTRY_DRAG_TYPE, dropDestination } from "../components/machineconfig/entryDrag";

export interface EntryDragOptions {
  move: (source: string, destination: string) => Promise<void> | void;
  remove: (path: string) => Promise<void> | void;
}

export function useEntryDragDrop(options: EntryDragOptions) {
  /** The path being dragged, ``null`` when no drag runs. */
  const dragging = ref<string | null>(null);
  /** The folder (or "__bin__") under the pointer. */
  const over = ref<string | null>(null);

  function onDragStart(path: string, event: DragEvent) {
    dragging.value = path;
    event.dataTransfer?.setData(ENTRY_DRAG_TYPE, path);
    event.dataTransfer?.setData("text/plain", path);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
  }

  function onDragEnd() {
    dragging.value = null;
    over.value = null;
  }

  function isEntryDrag(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes(ENTRY_DRAG_TYPE);
  }

  /** ``targetDir``: a folder path, "" for the root. */
  function canDrop(targetDir: string): boolean {
    return dragging.value !== null && dropDestination(dragging.value, targetDir) !== null;
  }

  function onDragOver(targetDir: string, event: DragEvent) {
    if (!isEntryDrag(event) || !canDrop(targetDir)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    over.value = targetDir;
  }

  function onDragLeave(targetDir: string) {
    if (over.value === targetDir) over.value = null;
  }

  async function onDrop(targetDir: string, event: DragEvent) {
    if (!isEntryDrag(event)) return;
    event.preventDefault();
    const source = event.dataTransfer?.getData(ENTRY_DRAG_TYPE) || dragging.value;
    onDragEnd();
    if (!source) return;
    const destination = dropDestination(source, targetDir);
    if (destination) await options.move(source, destination);
  }

  function onBinOver(event: DragEvent) {
    if (!isEntryDrag(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    over.value = "__bin__";
  }

  async function onBinDrop(event: DragEvent) {
    if (!isEntryDrag(event)) return;
    event.preventDefault();
    const source = event.dataTransfer?.getData(ENTRY_DRAG_TYPE) || dragging.value;
    onDragEnd();
    if (source) await options.remove(source);
  }

  return { dragging, over, onDragStart, onDragEnd, onDragOver, onDragLeave, onDrop, onBinOver, onBinDrop, canDrop };
}
