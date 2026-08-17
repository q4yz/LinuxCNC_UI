// Editor mapper. Translates between the wire shapes produced by
// ``/api/v1/programs/content/{filename}``,
// ``/api/v1/modules/machineconfig/profiles/content``,
// ``/api/v1/modules/macros/{name}/content``, etc. and the
// ``EditorDocument`` entity.
//
// The mapper is also the single place that knows the
// source-to-endpoint mapping; consumers only see the entity.

import { EditorDocument, EditorSource, isEditorSource } from "../entities/editor/EditorDocument";

/**
 * @param {string|null|undefined} raw
 * @returns {EditorSource|null}
 */
export function toEditorSource(raw) {
  return isEditorSource(raw) ? raw : null;
}

/**
 * @param {EditorSource} source
 * @param {string} path
 * @param {string} [content]
 * @param {boolean} [readOnly]
 * @returns {EditorDocument|null}
 */
export function toEditorDocument(source, path, content = "", readOnly = false) {
  if (!isEditorSource(source)) return null;
  if (typeof path !== "string" || path.length === 0) return null;
  return new EditorDocument({ source, path, content, readOnly });
}
