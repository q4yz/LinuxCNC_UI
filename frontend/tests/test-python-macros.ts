// Python macros (macros/<name>.py) in the UI: listed, created from a
// template, run and stopped, on macro buttons, highlighted in the editor.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const read = (p: string) => readFileSync(resolve(src, p), "utf-8");

test("py is a macro kind with its own list, and a stop action", () => {
  const store = read("stores/macrosStore.ts");
  assert.match(read("stores/macrosTypes.ts"), /"macro" \| "ngc" \| "mcode" \| "py"/);
  assert.match(store, /PY: "py"/);
  assert.match(store, /py: pyFiles/);
  assert.match(store, /loadList\(MACRO_KIND\.PY\)/);
  assert.match(store, /async function stopMacro\(name: string\)/);
  assert.match(read("facades/macrosFacade.ts"), /ModulesMacrosService\.stopMacro\(name\)/);
});

test("a new .py macro starts from a template with run(m)", () => {
  assert.match(read("stores/macrosStore.ts"), /export const PY_MACRO_TEMPLATE = `[\s\S]*def run\(m\):/);
  const manager = read("components/macros/MacroManagerPanel.vue");
  assert.match(manager, /value="py"/);
  assert.match(manager, /createKind\.value === MACRO_KIND\.PY \? PY_MACRO_TEMPLATE : "\\n"/);
});

test("the macro panel runs .py macros and can stop them", () => {
  const panel = read("components/macros/MacroPanel.vue");
  assert.match(panel, /v-if="row\.kind === 'macro' \|\| row\.kind === 'py'"/);
  assert.match(panel, /store\.runMacroOfKind\(kind, name\)/);
  assert.match(panel, /@click="store\.stopMacro\(row\.name\)"/);
});

test("macro buttons can start a Python macro", () => {
  assert.match(read("ui/MacroButtonEditor.vue"), /\{ value: "py", label: "Python" \}/);
  assert.match(read("ui/MacroButton.vue"), /macroKind === "py" \? "py"/);
});

test("the editor opens .py macros with Python highlighting", () => {
  assert.match(read("stores/editor.ts"), /lower\.endsWith\('\.py'\)[\s\S]*?kind: 'py'/);
  assert.match(read("components/Editor.vue"), /case 'python':\s*return \[StreamLanguage\.define\(python\), oneDark\]/);
});
