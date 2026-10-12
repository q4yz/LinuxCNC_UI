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
import { fileURLToPath, pathToFileURL } from "node:url";

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
  assert.match(text, /@router\.get\(\s*"\/thumbnail\/\{filename:path\}"/, "thumbnail route must exist (subfolders too)");
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
  assert.match(text, /file-thumb-\$\{file\.name\}/, "row thumbnail icon");
  assert.match(text, /data-test="file-preview-modal"/, "preview modal");
  assert.match(text, /data-test="preview-thumb"/, "large embedded image in the modal");
  assert.match(text, /ToolpathViewer/, "modal renders the 3D toolpath viewer");
  assert.match(text, /parseGcodeToolpath\(/, "preview parses the file with the shared parser");
  assert.match(text, /readFileContent\(/, "preview reads the file through the existing service call");
  // Row click opens the preview; action buttons must not bubble into it.
  assert.match(text, /@click="openPreview\(file\)"/, "row click opens the preview");
  assert.match(text, /@click\.stop/, "action buttons stop propagation");
});

test("row: Load / Unload outside, Edit / Download / Delete in the ⋮ menu, loaded file highlighted", () => {
  const text = read("components/FileManager.vue");

  // Load is the one visible row action; the loaded file offers Unload.
  // Rows are addressed by path (``project/part.ngc``) — names repeat across folders.
  assert.match(text, /data-test="`file-row-load-\$\{file\.path\}`"/, "row offers Load");
  assert.match(text, /isLoaded\(file\.path\) \? unloadFile\(file\.path\) : loadFile\(file\.path\)/);
  assert.match(text, /:disabled="!isMachineOnline \|\| busyFile !== null"/, "Load needs the machine service");

  // Everything else lives in the shared menu.
  assert.match(text, /<ActionMenu :items="ROW_MENU"/);
  for (const key of ["edit", "download", "copy", "move", "delete"]) {
    assert.match(text, new RegExp(`key: '${key}'`), `menu offers ${key}`);
  }
  assert.doesNotMatch(text, /data-test="`file-(edit|delete|download)-\$\{file\.name\}`"/, "no inline Edit / Delete / Download");
  assert.match(text, /key === 'download'\) await downloadFile\(file\.path\)/, "menu Download calls downloadFile");
  assert.match(text, /createObjectURL/, "download must build a Blob URL");

  // The loaded program is highlighted (same rule as the dashboard widget).
  assert.match(text, /useLoadedProgram\(\)/);
  assert.match(text, /loadedPathAmong\(/, "matched by path, not base name");
  assert.match(text, /:class="isLoaded\(file\.path\) \? 'bg-blue-900\/40/);
});

test("useLoadedProgram compares by base name", async () => {
  const { programBaseName } = await import(pathToFileURL(resolve(src, "composables/useLoadedProgram.ts")).href);
  assert.equal(programBaseName("/home/cnc/nc_files/part.ngc"), "part.ngc");
  assert.equal(programBaseName("C:\\nc\\part.ngc"), "part.ngc");
  assert.equal(programBaseName(null), "");
});

test("Load only works while the machine service is up", () => {
  const text = read("components/FileManager.vue");

  assert.match(text, /useMachineOnline/, "machine-online composable must be wired");
  // Load lives in the preview modal now, keyed to the previewed file.
  assert.match(
    text,
    /data-test="`file-load-\$\{previewFile\.path\}`"/,
    "the preview modal must offer Load for the previewed file",
  );
  assert.match(
    text,
    /:disabled="!isMachineOnline"[\s\S]{0,200}loadFile\(previewFile\.path\)/,
    "the preview's Load button must be disabled while the machine service is offline",
  );
  // Defense in depth: the handler itself refuses even if a disabled
  // button is somehow clicked (keyboard, race with the heartbeat).
  assert.match(
    text,
    /async function loadFile\([^)]*\)\s*\{\s*if \(!isMachineOnline\.value\) return/,
    "loadFile must refuse to run while the machine service is offline",
  );
});

test("file list shows an upload date and sorts newest-first", () => {
  const text = read("components/FileManager.vue");

  assert.match(text, />\s*Uploaded\s*</, "table must have an Uploaded column header");
  assert.match(text, /formatDate\(file\.modified\)/, "row must render the upload date");
  assert.match(text, /sortedFiles/, "list must be sorted before rendering");
  assert.match(
    text,
    /b\.modifiedMs\s*-\s*a\.modifiedMs/,
    "sort must be newest-first by modified",
  );
  assert.match(text, /v-for="file in sortedFiles"/, "table body must iterate the sorted list");
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
  // The Float32Array build runs in toolpathWorker.ts; the viewer only
  // wraps the transferred buffers.
  assert.match(text, /new THREE\.BufferAttribute\(positions, 3\)/, "mesh built from the worker's position buffer");
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
    /centerZ \+ distance/,
    "camera must sit mainly on +Z looking down towards Z−",
  );
  assert.match(
    text,
    /controls\.target\.set\(centerX, centerY, centerZ\)/,
    "camera must look at the part center",
  );
});

test("G-code files: project folders — browse, create (blue ⊕), upload into the open folder", () => {
  const text = read("components/FileManager.vue");

  // The open folder lives in the URL and filters the rows.
  assert.match(text, /useDirectoryQuery\('programsDir'\)/);
  assert.match(text, /v-for="folder in folders"/, "folders are listed");
  assert.match(text, /@click="openFolder\(folder\.path\)"/, "a folder row opens the folder");
  assert.match(text, /data-test="programs-breadcrumbs"/, "breadcrumbs back up the tree");

  // Folder ⋮ menu; deleting one with content goes through the shared warning.
  assert.match(text, /<ActionMenu :items="FOLDER_MENU"/);
  assert.match(text, /confirmDelete\(entry, files\.value\)/);
  assert.match(text, /filesFacade\.deleteFile\(entry\.path, recursive\)/);

  // Blue round "+" in the bottom-right creates a folder in the open folder.
  assert.match(text, /data-test="programs-new-folder"[\s\S]{0,200}@click="openFolderDialog"/);
  assert.match(text, /bottom-6 right-6[^"]*rounded-full bg-blue-600[^"]*text-white/);
  assert.match(text, /filesFacade\.createFolder\(path\)/);
  assert.match(text, /joinPath\(currentDirectory\.value, name\)/);

  // Uploads land in the open folder.
  assert.match(text, /filesFacade\.uploadFile\(file\.name, await withThumbnail\(file\), directory\)/);
});

test("the loaded program is matched by its path among the folders", async () => {
  const { matchLoadedPath } = await import(pathToFileURL(resolve(src, "composables/useLoadedProgram.ts")).href);
  const paths = ["a.ngc", "project/a.ngc", "b.ngc"];
  assert.equal(matchLoadedPath("/home/cnc/nc_files/project/a.ngc", paths), "project/a.ngc");
  assert.equal(matchLoadedPath("/home/cnc/nc_files/a.ngc", paths), "a.ngc");
  assert.equal(matchLoadedPath("C:\\nc_files\\project\\a.ngc", paths), "project/a.ngc");
  assert.equal(matchLoadedPath("/home/cnc/nc_files/xb.ngc", paths), null, "only at a folder boundary");
  assert.equal(matchLoadedPath(null, paths), null);
});
