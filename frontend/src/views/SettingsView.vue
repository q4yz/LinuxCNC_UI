<script setup>
import { computed, ref } from 'vue'
import registry from '../core/modules/registry'

// Active tab id. Defaults to the first module's id when panels exist
// so the user always sees content on first load.
const panels = computed(() => registry.settingsPanels())
const activeTab = ref(panels.value[0]?.id ?? null)

// Each module's settings panel is a thin placeholder until Phase 5
// ships a form generator. For now we render a short note per panel
// describing the module + a link to its API surface.
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

    <!-- Module-keyed tab list. Each tab is a placeholder until the
         module ships its own settings component (Phase 5). -->
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
        <p class="mt-2 text-sm text-gray-400">
          This module's settings UI is not implemented yet.
          The persisted store lives at:
        </p>
        <pre class="mt-3 bg-gray-900 text-gray-200 rounded p-3 text-xs overflow-x-auto"><code>GET  {{ apiBaseUrl(panel.id) }}
PUT  {{ apiBaseUrl(panel.id) }}   (bulk)
GET  {{ apiBaseUrl(panel.id) }}/{key}
PUT  {{ apiBaseUrl(panel.id) }}/{key}</code></pre>
      </div>
    </div>
  </div>
</template>