### Resolution Summary
Implemented a reusable dark-theme, Promise-based confirmation modal and integrated it with the editor's dirty-state router protection. Editor navigation, same-route file changes, close actions, and profile deletion now prompt before discarding work or deleting data.

### Files Modified
- `frontend/src/components/ModalConfirm.vue`: Props-driven dark-theme confirmation dialog with backdrop, Escape, dismiss, and action handling.
- `frontend/src/components/ModalConfirmHost.vue`: Global queue host for confirmation requests.
- `frontend/src/core/confirm.js`: Pinia-backed Promise confirmation queue and button-style constants.
- `frontend/src/router/guards/unsavedChangesGuard.js`: Reusable Vue Router leave guard for unsaved state predicates.
- `frontend/src/stores/editor.js`: Tracks `pristineContent` and exposes `isDirty` across load/open/save/close operations.
- `frontend/src/views/EditorView.vue`: Adds route and same-component navigation prompts and replaces native close confirmation.
- `frontend/src/modules/machineconfig/components/ProfilesExplorer.vue`: Replaces native delete confirmation with the shared modal.
- `frontend/src/App.vue`: Mounts the global modal host.
- `frontend/src/router/guards/unsavedChangesGuard.js`: Shared route guard helper.
- `frontend/tests/test-unsaved-changes-guard.mjs`: Static acceptance checks for the new confirmation architecture.
- `frontend/package.json`: Runs the repository's Node structural tests through `npm test`.
- `.agent/STATE.md`: Documents the unsaved-changes guard state.

### Architectural Decisions
- Dirty state remains in the Pinia editor store as a pristine-content snapshot, providing one source of truth for all editor consumers.
- Confirmation requests are serialized in a Pinia queue and resolve to booleans, allowing `onBeforeRouteLeave` to return the modal Promise directly.
- Native `window.confirm` was removed from both requested call sites; unrelated native rename/move prompts remain unchanged.

### Testing Verification
- [x] `npm --prefix frontend run build`
- [x] `npm --prefix frontend test` (99 tests passed)
- [x] `node --test "frontend/tests/test-unsaved-changes-guard.mjs"`
