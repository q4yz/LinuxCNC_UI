// Reactive per-filename thumbnail cache for the G-code file list.
//
// `ensure(filename)` fire-and-forgets the fetch (cached in
// helpers/fileThumbnails.ts) and records the result in a reactive
// map the template can bind to. Files without an embedded thumbnail
// resolve to `dataUrl: null` — the list shows a generic icon.

import { ref } from "vue";

import { fetchFileThumbnail, type FileThumbnail } from "../helpers/fileThumbnails";

const EMPTY: FileThumbnail = { dataUrl: null, width: null, height: null };

export function useFileThumbnails() {
  const thumbnails = ref<Record<string, FileThumbnail>>({});

  async function ensure(filename: string): Promise<void> {
    if (thumbnails.value[filename]) return;
    // Placeholder so repeat calls don't refetch while in flight.
    thumbnails.value[filename] = EMPTY;
    thumbnails.value[filename] = await fetchFileThumbnail(filename);
  }

  return { thumbnails, ensure };
}

export default useFileThumbnails;
