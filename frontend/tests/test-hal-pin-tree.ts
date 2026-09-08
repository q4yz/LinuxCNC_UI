// Unit tests for the HAL pin picker's folder tree (pure logic —
// ./hal-visual-editor/pinTree.ts). Drawer wiring (PinTreeItem usage,
// the sibling-pin match source) is covered structurally in
// test-hal-visual-editor.ts.
//
// Run with: ``node --test frontend/tests/test-hal-pin-tree.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const editorDir = resolve(repoRoot, "frontend/src/views/hal-visual-editor");

const { buildPinTree, lastSegment, folderContainsSuffix, collectAutoExpandPaths } = await import(
  pathToFileURL(resolve(editorDir, "pinTree.ts")).href
);

function pin(fullName, direction = "out") {
  return { id: fullName, fullName, type: "bit", direction };
}

test("lastSegment extracts the piece after the final dot", () => {
  assert.equal(lastSegment("halui.axis.z.step"), "step");
  assert.equal(lastSegment("motion.spindle-on"), "spindle-on");
  assert.equal(lastSegment("no-dots-here"), "no-dots-here");
});

test("buildPinTree turns every dot into a folder layer", () => {
  const tree = buildPinTree([pin("halui.axis.z.step"), pin("halui.axis.x.step")]);

  assert.equal(tree.children.length, 1, "one top-level folder: halui");
  const halui = tree.children[0];
  assert.equal(halui.kind, "folder");
  assert.equal(halui.segment, "halui");
  assert.equal(halui.path, "halui");

  const axis = halui.children.find((c) => c.kind === "folder" && c.segment === "axis");
  assert.ok(axis, "halui must contain an axis folder");
  assert.equal(axis.path, "halui.axis");

  // Numeric-aware sort keeps x before z, and both are folders (not
  // pins) since "step" is one level deeper still.
  assert.deepEqual(
    axis.children.map((c) => c.segment),
    ["x", "z"],
  );
  const x = axis.children.find((c) => c.segment === "x");
  assert.equal(x.children.length, 1);
  assert.equal(x.children[0].kind, "pin");
  assert.equal(x.children[0].segment, "step");
  assert.equal(x.children[0].pin.fullName, "halui.axis.x.step");
});

test("buildPinTree sorts folders before pins, and numerically within each", () => {
  const tree = buildPinTree([
    pin("stepgen.10.step"),
    pin("stepgen.2.step"),
    pin("stepgen.1.step"),
    pin("bare-pin"),
  ]);

  // "bare-pin" (a root-level pin) sorts after the "stepgen" folder.
  assert.deepEqual(
    tree.children.map((c) => c.segment),
    ["stepgen", "bare-pin"],
  );
  const stepgen = tree.children[0];
  assert.deepEqual(
    stepgen.children.map((c) => c.segment),
    ["1", "2", "10"],
    "instance numbers must sort numerically (1, 2, 10), not lexically (1, 10, 2)",
  );
});

test("a pin can sit alongside a deeper folder with the same segment", () => {
  // Rare HAL naming edge case: "foo.bar" is itself a pin, AND
  // "foo.bar.baz" is a different, deeper pin. Neither should be lost.
  const tree = buildPinTree([pin("foo.bar"), pin("foo.bar.baz")]);
  const foo = tree.children.find((c) => c.segment === "foo");
  assert.equal(foo.children.length, 2);
  assert.ok(foo.children.some((c) => c.kind === "pin" && c.segment === "bar"));
  assert.ok(foo.children.some((c) => c.kind === "folder" && c.segment === "bar"));
});

test("folderContainsSuffix finds a matching pin at any depth", () => {
  const tree = buildPinTree([pin("halui.axis.z.step"), pin("halui.axis.z.dir")]);
  const halui = tree.children[0];
  assert.equal(folderContainsSuffix(halui, "step"), true);
  assert.equal(folderContainsSuffix(halui, "dir"), true);
  assert.equal(folderContainsSuffix(halui, "enable"), false);
  assert.equal(folderContainsSuffix(halui, null), false, "no suffix means no match, ever");
});

test("collectAutoExpandPaths pops open every ancestor of a matched pin", () => {
  const pins = [pin("halui.axis.z.step"), pin("halui.axis.x.step"), pin("halui.axis.y.dir")];
  const paths = collectAutoExpandPaths(pins, "step", false);

  assert.ok(paths.has("halui"));
  assert.ok(paths.has("halui.axis"));
  assert.ok(paths.has("halui.axis.z"));
  assert.ok(paths.has("halui.axis.x"));
  // The y/dir branch doesn't end in "step" — its folder isn't forced open.
  assert.ok(!paths.has("halui.axis.y"));
});

test("collectAutoExpandPaths expands everything while searching, matched or not", () => {
  const pins = [pin("halui.axis.z.step"), pin("motion.spindle-on")];
  const paths = collectAutoExpandPaths(pins, null, true);
  assert.ok(paths.has("halui"));
  assert.ok(paths.has("halui.axis"));
  assert.ok(paths.has("halui.axis.z"));
  // "motion.spindle-on" has one dot → one ancestor folder: "motion".
  assert.ok(paths.has("motion"));
});

test("collectAutoExpandPaths does nothing without a search or a match", () => {
  const paths = collectAutoExpandPaths([pin("halui.axis.z.step")], null, false);
  assert.equal(paths.size, 0);
});
