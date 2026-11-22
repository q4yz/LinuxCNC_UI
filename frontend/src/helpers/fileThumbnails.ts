// Slicer-thumbnail cache for the G-code file list
// (``filesFacade.thumbnail``: ``GET /api/v1/programs/thumbnail/{filename}``,
// system backend — pure filesystem, no LinuxCNC needed).
//
// Safe to call while the machine backend is offline. Results are cached
// per filename for the session; a failed request resolves to the empty
// thumbnail (generic icon) rather than rejecting — the list must render
// regardless.

import { filesFacade } from '../facades/filesFacade'

export interface FileThumbnail {
  /** `data:image/png;base64,…` or `null` when the file has none. */
  dataUrl: string | null
  width: number | null
  height: number | null
}

const EMPTY: FileThumbnail = { dataUrl: null, width: null, height: null }

const cache = new Map<string, Promise<FileThumbnail>>()

export function fetchFileThumbnail(filename: string): Promise<FileThumbnail> {
  const hit = cache.get(filename)
  if (hit) return hit

  const promise = (async (): Promise<FileThumbnail> => {
    try {
      const body = await filesFacade.thumbnail(filename)
      return {
        dataUrl: body.data_url ?? null,
        width: body.width ?? null,
        height: body.height ?? null,
      }
    } catch {
      return EMPTY
    }
  })()

  cache.set(filename, promise)
  return promise
}

/** Test/refresh seam: drop every cached thumbnail. */
export function clearThumbnailCache(): void {
  cache.clear()
}
