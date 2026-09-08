// Structural guard for the machine template flow (compiler
// replacement): the Profiles explorer must drive generation with the
// machine-exists confirm flow, the Machines explorer must exist and
// route through the writable ``machines`` editor source, and the view
// must render the three-section layout without the deprecated
// compiler panels.
//
// Run with: ``node --test frontend/tests/test-machine-templates.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");

const read = (rel) => readFileSync(resolve(src, rel), "utf-8");

test("store owns the machines tree + generate flow with conflict contract", () => {
  const text = read("stores/machineconfigStore.ts");

  assert.match(text, /loadMachinesTree/, "store must load the machines tree");
  assert.match(
    text,
    /async function generateMachine\(/,
    "store must expose the generate action",
  );
  assert.match(
    text,
    /status: "conflict"/,
    "generate must surface the machine-exists 409 as a conflict outcome",
  );
  assert.match(text, /confirmOverride/, "generate must accept the override flag");
  // CRUD parity with the profiles explorer.
  for (const action of [
    "saveMachine",
    "createMachineFolder",
    "createMachineFile",
    "uploadMachines",
    "renameMachine",
    "deleteMachine",
  ]) {
    assert.match(text, new RegExp(`function ${action}\\(`), `store action ${action} missing`);
  }
});

test("facade surfaces the structured machine_exists 409", () => {
  const text = read("facades/machineconfigFacade.ts");

  assert.match(text, /generateMachine/, "facade must expose generateMachine");
  assert.match(text, /machine_exists/, "facade must detect the machine_exists kind");
  assert.match(text, /existsConflict/, "facade must carry the conflict payload");
  assert.match(text, /listMachines/, "facade must expose the machines tree read");
});

test("editor routes the writable machines source", () => {
  const text = read("stores/editor.ts");

  assert.match(text, /MACHINES: 'machines'/, "machines must be a first-class source");
  assert.match(
    text,
    /case EDITOR_SOURCES\.MACHINES: return readMachineContent/,
    "dispatchRead must route machines",
  );
  assert.match(
    text,
    /case EDITOR_SOURCES\.MACHINES: return writeMachineContent/,
    "dispatchWrite must route machines (templates are editable)",
  );
  // ``machines`` must NOT be listed in the read-only set.
  const readOnly = text.match(/READ_ONLY_SOURCES = new Set<string>\(\[([^\]]*)\]/);
  assert.ok(readOnly, "READ_ONLY_SOURCES set must remain declarative");
  assert.doesNotMatch(readOnly[1], /MACHINES/, "machines must stay writable");
});

test("MachinesExplorer exists and mirrors the explorer contract", () => {
  const path = resolve(src, "components/machineconfig/MachinesExplorer.vue");
  assert.ok(existsSync(path), "MachinesExplorer.vue must exist");
  const text = readFileSync(path, "utf-8");
  assert.match(text, /machinesTree/, "explorer must bind the machines tree");
  assert.match(text, /emit\("edit"/, "explorer must emit edit events");
  assert.doesNotMatch(
    text,
    /onCompile|store\.compile\(/,
    "machines explorer must not offer the deprecated compile action",
  );
});

test("both explorers keep their open folder in the URL", () => {
  // Opening a file unmounts the explorers, so local state would drop
  // the operator back at the root on return. The directory lives in
  // the query string instead, which also makes browser back/forward
  // and bookmarks work on a folder.
  for (const [file, key] of [
    ["components/machineconfig/ProfilesExplorer.vue", "profilesDir"],
    ["components/machineconfig/MachinesExplorer.vue", "machinesDir"],
  ]) {
    const text = read(file);
    assert.match(
      text,
      new RegExp(`useDirectoryQuery\\(["']${key}["']\\)`),
      `${file} must bind currentDirectory to the ${key} query param`,
    );
    assert.doesNotMatch(
      text,
      /const currentDirectory = ref\(/,
      `${file} must not hold the directory in local-only state`,
    );
  }
});

test("closing an editor steps back instead of pushing a fixed route", () => {
  // A hard-coded push drops the explorer's folder (it lives in the
  // URL) and ignores which page actually opened the editor. Scoped to
  // the closeEditor body — pushes elsewhere (e.g. the no-target
  // empty state's "open Machine Config" link) are fine.
  for (const file of ["views/EditorView.vue", "views/VisualHalEditor.vue"]) {
    const text = read(file);
    const body = text.match(/function closeEditor\([^)]*\)[^{]*\{[\s\S]*?\n\}/);
    assert.ok(body, `${file} must declare closeEditor()`);
    assert.match(body[0], /closeToPrevious\(/, `${file}'s closeEditor must use closeToPrevious`);
    assert.doesNotMatch(
      body[0],
      /router\.push\(/,
      `${file}'s closeEditor must not hard-code a route push`,
    );
  }
  // The helper only falls back to a route when there is no history to
  // return to (deep link / fresh tab).
  const helper = read("helpers/closeToPrevious.ts");
  assert.match(helper, /history\.state/, "must consult the router's history state");
  assert.match(helper, /router\.back\(\)/, "must step back when there is somewhere to go");
  assert.match(helper, /fallbackName/, "must fall back for a directly-opened editor");
});

test("Profiles explorer generates machines with an override confirm", () => {
  const text = read("components/machineconfig/ProfilesExplorer.vue");

  assert.match(text, /Generate</, "profiles rows must carry a Generate button");
  assert.match(text, /onGenerate/, "profiles must call the generate action");
  assert.match(
    text,
    /Machine exists/,
    "the machine-exists confirm modal must be wired",
  );
  assert.doesNotMatch(
    text,
    /onCompile/,
    "the deprecated Compile button must be gone",
  );
});

test("view renders Profiles / Machines without compiler or active panels", () => {
  // MachineConfigView.vue was folded into ConfigView.vue — the Config
  // page is now the single home for the machine-config explorers.
  // ActivePanel (and the machine_config/active/ deploy step it
  // rendered) was removed — a machine's config lives directly under
  // machine_config/machines/<name>/ and is addressed by name now.
  const text = read("views/ConfigView.vue");

  assert.match(text, /ProfilesExplorer/, "Profiles section required");
  assert.match(text, /MachinesExplorer/, "Machines section required");
  assert.doesNotMatch(
    text,
    /CompilerPanel|CompiledOutputViewer|DeploymentPanel|ActivePanel/,
    "deprecated compiler and active panels must not render",
  );
  assert.doesNotMatch(
    text,
    /openInEditor\(\{ source: 'profiles', name: path \}\)/,
    "openEditor must take an explicit source argument",
  );
});
