// Structural guard for the Bed Mesh page (`.agent/component/bed_mesh.md`):
// list / select / use / delete / edit saved meshes, the heatmap, and the
// compensation switch.
//
// Run with: ``node --test frontend/tests/test-bed-mesh-ui.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("the page is routed and in the sidebar without a running machine", () => {
  assert.match(read("router/index.ts"), /path: '\/bedmesh', name: 'bedmesh', component: BedMeshView/);
  assert.match(read("components/AppSidebar.vue"), /id: 'bedmesh'[^}]*activeMachineOnly: false/);
});

test("the facade splits meshes (system service) from the switch (machine backend)", () => {
  const facade = read("facades/bedMeshFacade.ts");
  for (const call of ["listBedMeshes", "readBedMesh", "saveBedMesh", "deleteBedMesh", "activateBedMesh", "createBedMesh"]) {
    assert.match(facade, new RegExp(`ModulesBedmeshService\\.${call}`), `${call} must go to the system service`);
  }
  assert.match(facade, /BedmeshService\.setBedMeshEnable\(\{ enabled \}\)/);
});

test("the view lists, uses, deletes, edits and creates meshes", () => {
  const view = read("views/BedMeshView.vue");
  assert.match(view, /data-testid="bed-mesh-list"/);
  assert.match(view, /:data-testid="`bed-mesh-activate-\$\{name\}`"/);
  assert.match(view, /:disabled="busy \|\| active === name"/, "the active mesh cannot be deleted");
  assert.match(view, /<BedMeshHeatmap v-if="shown" :grid="shown" :editable="!!draft" @update:cell="setCell" \/>/);
  assert.match(view, /data-testid="bed-mesh-save"/);
  assert.match(view, /v-model\.number="newSpec\.y_max" type="number" step="any"/, "decimal limits must be accepted");
  assert.match(view, /compensation === null \? "unavailable"/, "no machine backend: the switch says so");
});

test("the heatmap is a clickable canvas image with a gradient, not a cell grid", () => {
  const heatmap = read("components/bedmesh/BedMeshHeatmap.vue");
  assert.match(heatmap, /<canvas[\s\S]*data-testid="bed-mesh-canvas"[\s\S]*@click="onClick"/);
  assert.doesNotMatch(heatmap, /<table|v-for="\(x, col\) in grid\.xs"/, "no table / input per probe point");
  assert.match(heatmap, /gradientColor\(interpolate\(props\.grid, x, y\), maxAbs\.value\)/, "every pixel interpolated");
  assert.match(heatmap, /PAD\.top \+ ph - fy \* ph/, "Y up: the front-left corner is bottom-left");
  assert.match(heatmap, /:style="\{ background: GRADIENT_CSS \}"/, "the legend shows the same gradient");
  assert.match(heatmap, /data-testid="bed-mesh-spot"/);
  assert.match(heatmap, /emit\("update:cell", info\.point\.row, info\.point\.col, value\)/, "edit the nearest probe point");
});

test("probing a mesh: BED_MESH_CALIBRATE with a profile, polled until done", () => {
  const facade = readFileSync(resolve(src, "facades/bedMeshFacade.ts"), "utf-8");
  assert.match(facade, /BedmeshService\.calibrateBedMesh\(\{ profile \}\)/);
  assert.match(facade, /BedmeshService\.getBedMeshCalibrate\(\)/);
  const view = readFileSync(resolve(src, "views/BedMeshView.vue"), "utf-8");
  assert.match(view, /data-testid="bed-mesh-probe"[\s\S]*?@click="probe"/);
  assert.match(view, /bedMeshFacade\.calibrate\(profile\)/);
  assert.match(view, /bedMeshFacade\.isCalibrating\(\)/);
});
