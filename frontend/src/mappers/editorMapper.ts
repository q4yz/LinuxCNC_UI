// Editor mapper. Translates between the wire shapes produced by
// ``/api/v1/programs/content/{filename}``,
// ``/api/v1/modules/machineconfig/profiles/content``,
// ``/api/v1/modules/macros/{name}/content``, etc. and the
// ``EditorDocument`` entity.
//
// The mapper is also the single place that knows the
// source-to-endpoint mapping; consumers only see the entity.

import {
  EditorDocument,
  type EditorSource,
  isEditorSource,
} from "../entities/editor/EditorDocument";

export function toEditorSource(raw: unknown): EditorSource | null {
  return isEditorSource(raw) ? raw : null;
}

export function toEditorDocument(
  source: unknown,
  path: unknown,
  content: string = "",
  readOnly: boolean = false,
): EditorDocument | null {
  if (!isEditorSource(source)) return null;
  if (typeof path !== "string" || path.length === 0) return null;
  return new EditorDocument({ source, path, content, readOnly });
}
