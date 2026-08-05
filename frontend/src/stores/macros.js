// Pinia store for the macro subsystem (issue #7).
//
// State shape:
//
//   macros:        Array<{name, modified, size}>   — listing from the backend
//   selectedName:  string | null                   — currently-open macro
//   content:       string                          — editor buffer
//   savedContent:  string                          — last persisted content
//   running:       boolean                         — ``runMacro`` in flight
//   dirty:         boolean                         — computed: content !== saved
//   logs:          Array<{level, message}>          — last run's log entries
//   lastResult:    object | null                   — full ``MacroRunResponse``
//   error:         string | null                   — last error message
//
// The store is the single source of truth for the editor and the
// dashboard grid. Both surfaces read from it through ``storeToRefs``
// so the reactivity is preserved.

import { defineStore } from 'pinia';

import {
  deleteMacro as apiDeleteMacro,
  getMacro as apiGetMacro,
  listMacros as apiListMacros,
  runMacro as apiRunMacro,
  saveMacro as apiSaveMacro,
} from '../services/macros';

export const useMacroStore = defineStore('macros', {
  state: () => ({
    macros: [],
    selectedName: null,
    content: '',
    savedContent: '',
    running: false,
    logs: [],
    lastResult: null,
    error: null,
    isLoading: false,
    isSaving: false,
  }),

  getters: {
    /** ``name`` of the macro currently in the editor (or ``null``). */
    activeName: (state) => state.selectedName,

    /** ``true`` when the editor has unsaved changes. */
    dirty: (state) => state.content !== state.savedContent,

    /** True when the store has finished the first list load. */
    hasLoaded: (state) => state.macros.length > 0 || !state.isLoading,
  },

  actions: {
    // ------------------------------------------------------------------ //
    // Listing                                                             //
    // ------------------------------------------------------------------ //

    async loadMacros() {
      this.isLoading = true;
      this.error = null;
      try {
        const list = await apiListMacros();
        this.macros = Array.isArray(list) ? list : [];
      } catch (err) {
        this.error = err.message || String(err);
      } finally {
        this.isLoading = false;
      }
    },

    // ------------------------------------------------------------------ //
    // Selection / editing                                                 //
    // ------------------------------------------------------------------ //

    async select(name) {
      if (!name) {
        this.selectedName = null;
        this.content = '';
        this.savedContent = '';
        this.logs = [];
        this.lastResult = null;
        this.error = null;
        return;
      }

      this.isLoading = true;
      this.error = null;
      try {
        const data = await apiGetMacro(name);
        this.selectedName = data.name;
        this.content = data.content || '';
        this.savedContent = data.content || '';
        this.logs = [];
        this.lastResult = null;
      } catch (err) {
        this.error = err.message || String(err);
      } finally {
        this.isLoading = false;
      }
    },

    /**
     * Update the editor buffer (called by ``v-model`` on the
     * CodeMirror wrapper). Does not flag an error on its own.
     */
    updateContent(value) {
      this.content = typeof value === 'string' ? value : '';
    },

    /**
     * Start a new macro from a template. The caller is responsible
     * for persisting it (via :meth:`save`) — this action only
     * populates the editor buffer.
     */
    newFromTemplate(template) {
      if (!template || typeof template.content !== 'string') return;
      this.selectedName = `${template.name || 'untitled.macro'}`;
      this.content = template.content;
      this.savedContent = '';
      this.logs = [];
      this.lastResult = null;
    },

    // ------------------------------------------------------------------ //
    // Save / delete / run                                                 //
    // ------------------------------------------------------------------ //

    async save() {
      if (!this.selectedName) {
        this.error = 'No macro selected.';
        return false;
      }
      this.isSaving = true;
      this.error = null;
      try {
        const data = await apiSaveMacro(this.selectedName, this.content);
        this.selectedName = data.name;
        this.savedContent = data.content;
        this.content = data.content;
        await this.loadMacros();
        return true;
      } catch (err) {
        this.error = err.message || String(err);
        return false;
      } finally {
        this.isSaving = false;
      }
    },

    async remove(name) {
      this.error = null;
      try {
        await apiDeleteMacro(name);
        if (this.selectedName === name) {
          this.selectedName = null;
          this.content = '';
          this.savedContent = '';
        }
        await this.loadMacros();
        return true;
      } catch (err) {
        this.error = err.message || String(err);
        return false;
      }
    },

    async run(name) {
      const target = name || this.selectedName;
      if (!target) {
        this.error = 'No macro selected.';
        return null;
      }
      this.running = true;
      this.error = null;
      try {
        const result = await apiRunMacro(target);
        this.logs = Array.isArray(result?.logs) ? result.logs : [];
        this.lastResult = result;
        return result;
      } catch (err) {
        this.error = err.message || String(err);
        return null;
      } finally {
        this.running = false;
      }
    },

    clearLogs() {
      this.logs = [];
      this.lastResult = null;
    },
  },
});

export default useMacroStore;
