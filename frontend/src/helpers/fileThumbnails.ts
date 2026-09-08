// Slicer-thumbnail fetch helper for the G-code file list.
//
// Talks to `GET /api/v1/programs/thumbnail/{filename}` (system
// backend — pure filesystem, no LinuxCNC needed). Raw `fetch`
// because the generated client is regenerated from the live backends
// and predates this route (same situation as
// facades/machineLifecycleFacade.ts); migrate once
// `npm run generate-api` runs against a backend that has it.
//
// Pure-filesystem endpoint → safe to call while the machine backend
// is offline. Results are cached per filename for the session; a
// failed fetch resolves to the empty thumbnail (generic icon) rather
// than rejecting — the list must render regardless.

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
      const response = await fetch(
        `/api/v1/programs/thumbnail/${encodeURIComponent(filename)}`,
      )
      if (!response.ok) return EMPTY
      const body = (await response.json()) as {
        data_url?: string | null
        width?: number | null
        height?: number | null
      }
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
