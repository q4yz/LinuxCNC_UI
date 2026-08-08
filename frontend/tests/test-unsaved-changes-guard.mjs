import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = async (path) => readFile(new URL(`../src/${path}`, import.meta.url), "utf8");

test("unsaved changes guard structure is present", async () => {
  const store = await source("stores/editor.js");
  const confirm = await source("core/confirm.js");
  const modal = await source("components/ModalConfirm.vue");
  const app = await source("App.vue");
  const editor = await source("views/EditorView.vue");
  const profiles = await source("modules/machineconfig/components/ProfilesExplorer.vue");

  assert.match(store, /pristineContent/);
  assert.match(store, /isDirty/);
  assert.match(confirm, /export function useConfirm/);
  assert.match(confirm, /ModalButtonStyle/);
  for (const text of ["title", "question", "description", "confirmButtonText", "rejectButtonText"]) assert.match(modal, new RegExp(text));
  assert.match(app, /ModalConfirmHost/);
  assert.match(editor, /onBeforeRouteLeave|useUnsavedChangesGuard/);
  assert.doesNotMatch(editor, /window\.confirm/);
  assert.doesNotMatch(profiles, /window\.confirm/);
});
