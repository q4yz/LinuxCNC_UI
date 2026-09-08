// Structural guard for the G-code file-preview feature.
//
// Slicers (Cura / PrusaSlicer / Orca) embed a preview PNG at the top
// of the exported program as a base64 comment block. The backend
// extracts it (`GET /api/v1/programs/thumbnail/{filename}` — a
// head-scan, never a full multi-MB read), the file list shows it as
// the row icon, and clicking a row opens a preview modal with the
// image plus the parsed 3D toolpath — rendered by a JOG-FREE viewer
// extracted from NgcCoordinateSystemViewer (the full coordinate
// viewer binds window-level keydown handlers that jog the machine,
// so it must never be mounted in a passive dialog).
//
// Run with: ``node --test frontend/tests/test-file-preview.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");

const read = (rel) => readFileSync(resolve(src, rel), "utf-8");

// ------------------------------------------------------------------ //
// Backend thumbnail endpoint                                             //
// ------------------------------------------------------------------ //

test("backend exposes a head-scan thumbnail endpoint on the programs router", () => {
  const text = readFileSync(
    resolve(repoRoot, "backend/system/routers/FilesRouter.py"),
    "utf-8",
  );
  assert.match(text, /@router\.get\(\s*"\/thumbnail\/\{filename\}"/, "thumbnail route must exist");
  assert.match(text, /operation_id="getFileThumbnail"/, "operation id pinned for client generation");
  assert.match(text, /THUMBNAIL_HEAD_BYTES/, "head-scan cap constant must exist");
  assert.match(text, /read_head\(/, "endpoint must read only the file head");
  assert.match(text, /FileThumbnailResponse/, "response model must exist");
});

test("thumbnail extractor supports both slicer comment conventions", () => {
  const text = readFileSync(
    resolve(repoRoot, "backend/system/services/gcode_thumbnail.py"),
    "utf-8",
  );
  // PrusaSlicer / Orca / Cura-plugin convention.
  assert.match(text, /thumbnail\s\\s\+_?begin|thumbnail\s+\+_?begin|thumbnail\s+_?begin/, "begin marker");
  assert.match(text, /_?end/, "end marker");
  assert.match(text, /THUMBNAIL_BLOCK/, "Cura THUMBNAIL_BLOCK wrappers must be documented/handled");
  assert.match(text, /validate=True/, "base64 must be validated");
  assert.match(text, /largest/i, "the largest block wins");
});

// ------------------------------------------------------------------ //
// Frontend: thumbnails + preview modal                                   //
// ------------------------------------------------------------------ //

test("FileManager shows thumbnails and opens the preview modal", () => {
  const text = read("components/FileManager.vue");

  assert.match(text, /useFileThumbnails/, "thumbnail composable wired");
  assert.match(text, /file-thumb-\$\{file\.filename\}/, "row thumbnail icon");
  assert.match(text, /data-test="file-preview-modal"/, "preview modal");
  assert.match(text, /data-test="preview-thumb"/, "large embedded image in the modal");
  assert.match(text, /ToolpathViewer/, "modal renders the 3D toolpath viewer");
  assert.match(text, /parseGcodeToolpath\(/, "preview parses the file with the shared parser");
  assert.match(text, /readFileContent\(/, "preview reads the file through the existing service call");
  // Row click opens the preview; action buttons must not bubble into it.
  assert.match(text, /@click="openPreview\(file\)"/, "row click opens the preview");
  assert.match(text, /@click\.stop/, "action buttons stop propagation");
});

test("thumbnail helper targets the thumbnail endpoint and caches per file", () => {
  const text = read("helpers/fileThumbnails.ts");
  assert.match(
    text,
    /\/api\/v1\/programs\/thumbnail\//,
    "helper must hit the thumbnail endpoint",
  );
  assert.match(text, /encodeURIComponent/, "filenames must be URL-encoded");
  assert.match(text, /cache/, "per-filename session cache must exist");
  assert.ok(
    !/"data:image\/png/.test(text),
    "helper must not fabricate thumbnails — the backend returns the data URL",
  );
});

// ------------------------------------------------------------------ //
// ToolpathViewer: reuse without the jog hazard                           //
// ------------------------------------------------------------------ //

test("ToolpathViewer is dependency-free and binds no keyboard handlers", () => {
  const path = resolve(src, "components/ToolpathViewer.vue");
  assert.ok(existsSync(path), "components/ToolpathViewer.vue must exist");
  const text = readFileSync(path, "utf-8");

  assert.match(text, /segments: ParsedSegment\[\]/, "props must take parsed segments");
  assert.match(
    text,
    /import type \{ ParsedSegment \} from ["']\.\.\/parsers\/gcodeParser["']/,
    "must reuse the coordinate viewer's parser types",
  );
  assert.match(text, /new THREE\.BufferAttribute\(flat, 3\)/, "same flat-array mesh build");
  assert.match(text, /OrbitControls/, "orbit controls for inspection");

  // The whole point of the extraction: NO machine stores, NO key
  // listeners, NO network — a passive dialog can never jog.
  for (const banned of [
    /useMachineStore/,
    /useBaseThreadStore/,
    /useConsoleStore/,
    /addEventListener\(["']keydown/,
    /addEventListener\(["']keyup/,
    /ProgramFilesService/,
    /fetch\(/,
  ]) {
    assert.ok(!banned.test(text), `ToolpathViewer must not contain ${banned}`);
  }
});

// ------------------------------------------------------------------ //
// Thumbnail generation at upload + preview camera                        //
// ------------------------------------------------------------------ //

test("gcodeThumbnail helper generates the standard block when missing", () => {
  const text = read("helpers/gcodeThumbnail.ts");
  assert.match(text, /export function hasEmbeddedThumbnail\(/);
  assert.match(text, /export function buildThumbnailBlock\(/);
  assert.match(text, /export function ensureEmbeddedThumbnail\(/);
  assert.match(
    text,
    /width = 220,\s*\r?\n?\s*height = 124/,
    "default size must be 220x124 (PrusaSlicer large)",
  );
  assert.match(
    text,
    /thumbnail begin \$\{width\}x\$\{height\}/,
    "block must carry the standard begin marker with the declared size",
  );
  assert.match(text, /toDataURL\("image\/png"\)/, "rendered via canvas PNG");
  assert.match(
    text,
    /hasEmbeddedThumbnail\(text\)\)\s*return text/,
    "files that already have a thumbnail must stay untouched",
  );
});

test("upload embeds the generated thumbnail before storing the file", () => {
  const text = read("components/FileManager.vue");
  assert.match(text, /await file\.text\(\)/, "upload must read the file text");
  assert.match(
    text,
    /ensureEmbeddedThumbnail\(rawText, segments\)/,
    "thumbnail embedded (if missing) before upload",
  );
  assert.match(
    text,
    /new File\(\[finalText\], file\.name/,
    "the modified text is uploaded as a File carrying the original filename (a nameless Blob gets stored as 'blob')",
  );
});

test("ToolpathViewer frames the part top-down from Z+ with no base grid", () => {
  const text = read("components/ToolpathViewer.vue");
  assert.ok(!/GridHelper/.test(text), "base grid must be removed");
  assert.match(
    text,
    /center\.z \+ distance/,
    "camera must sit mainly on +Z looking down towards Z−",
  );
  assert.match(
    text,
    /controls\.target\.copy\(center\)/,
    "camera must look at the part center",
  );
});
