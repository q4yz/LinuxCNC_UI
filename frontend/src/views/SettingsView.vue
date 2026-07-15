<script setup>
// Settings shell. Each mounted module whose manifest declares
// ``settingsPanel: true`` gets a tab. When the module exports a
// ``settingsPanel`` component (see issue #35 / Phase 5 polish) we
// render it; otherwise we show the legacy placeholder describing
// the persisted store and listing the four canonical endpoints.
import { computed, ref, shallowRef } from 'vue'
import registry from '../core/modules/registry'

// ``shallowRef`` keeps Vue from deep-tracking the component object
// — important because async component loaders return new function
// identities on every re-render otherwise.
const panels = computed(() => registry.settingsPanels())
const activeTab = ref(panels.value[0]?.id ?? null)
const panelComponents = shallowRef(new Map())

// Resolve the panel component for ``id`` on demand. Modules that
// ship a component return one through the registry; the rest fall
// through to the placeholder markup below.
function panelFor(id) {
  return panels.value.find((p) => p.id === id)?.panel ?? null
}

function apiBaseUrl(moduleId) {
  return `/api/v1/modules/${moduleId}/settings`
}
</script>

<template>
  <div class="space-y-6">
    <header class="flex items-baseline justify-between">
      <h1 class="text-2xl font-bold">Settings</h1>
      <span class="text-sm text-gray-400">
        {{ panels.length }} module{{ panels.length === 1 ? '' : 's' }} mounted
      </span>
    </header>

    <!-- Empty state: no modules declared a settingsPanel. -->
    <div
      v-if="panels.length === 0"
      class="bg-gray-800 rounded-lg p-8 text-center"
      data-testid="settings-empty"
    >
      <h2 class="text-xl font-semibold text-gray-300">
        Settings (no modules mounted)
      </h2>
      <p class="mt-2 text-sm text-gray-500">
        Drop a module under
        <code class="bg-gray-700 px-1 py-0.5 rounded">frontend/src/modules/&lt;id&gt;</code>
        and it will appear here automatically.
      </p>
    </div>

    <!-- Module-keyed tab list. -->
    <div v-else class="bg-gray-800 rounded-lg overflow-hidden">
      <nav class="flex border-b border-gray-700">
        <button
          v-for="panel in panels"
          :key="panel.id"
          @click="activeTab = panel.id"
          class="px-4 py-3 text-sm font-medium transition-colors"
          :class="
            activeTab === panel.id
              ? 'bg-blue-600 text-white border-b-2 border-blue-400'
              : 'text-gray-400 hover:bg-gray-700 hover:text-gray-200'
          "
          :data-testid="`settings-tab-${panel.id}`"
        >
          {{ panel.title }}
        </button>
      </nav>
      <div
        v-for="panel in panels"
        :key="panel.id"
        v-show="activeTab === panel.id"
        class="p-6"
        :data-testid="`settings-panel-${panel.id}`"
      >
        <h2 class="text-lg font-semibold text-gray-200">
          {{ panel.title }} settings
        </h2>

        <!-- Module-supplied component (Phase 5 polish — issue #35).
             Modules that export ``settingsPanel`` get a fully
             themed UI; the rest keep the placeholder. -->
        <component
          v-if="panelFor(panel.id)"
          :is="panelFor(panel.id)"
          class="mt-4"
        />

        <!-- Legacy placeholder for modules that haven't shipped a
             panel component yet. -->
        <template v-else>
          <p class="mt-2 text-sm text-gray-400">
            This module's settings UI is not implemented yet.
            The persisted store lives at:
          </p>
          <pre class="mt-3 bg-gray-900 text-gray-200 rounded p-3 text-xs overflow-x-auto"><code>GET  {{ apiBaseUrl(panel.id) }}
PUT  {{ apiBaseUrl(panel.id) }}   (bulk)
GET  {{ apiBaseUrl(panel.id) }}/{key}
PUT  {{ apiBaseUrl(panel.id) }}/{key}</code></pre>
        </template>
      </div>
    </div>
  </div>
</template>
