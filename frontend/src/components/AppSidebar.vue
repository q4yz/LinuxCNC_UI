<script setup>
import { ref, computed } from 'vue'
import registry from '../core/modules/registry'

defineProps({
  currentView: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['navigate'])

// Built-in entries are always present (they back the existing static
// sidebar). Module-contributed entries are merged in sorted by their
// ``order`` field, so a module with ``order: 5`` floats above the
// built-ins (which all default to ``order: 100``).
//
// ``config`` was the legacy "Machine Config" entry that pointed at
// the still-unmigrated :class:`ConfigView`. Issue #41 introduces the
// ``machineconfig`` module whose sidebar entry supersedes it — the
// module ships its own :class:`MachineConfigView` with the new
// profiles / compiler / deploy / active workflow. Operators who
// explicitly want the legacy ConfigView can still reach it at
// ``/#config`` (the nav button just no longer appears in the rail).
const builtinItems = [
  { id: 'dashboard', label: 'Dashboard', icon: '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>', order: 100 },
  { id: 'files', label: 'G-Code Files', icon: '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>', order: 100 },
  // Settings is a built-in shell view; it shows "Settings (no modules
  // mounted)" when the registry is empty, and one tab per module that
  // declares ``settingsPanel`` otherwise.
  { id: 'settings', label: 'Settings', icon: '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>', order: 200 }
]

const moduleEntries = computed(() => registry.sidebarEntries())

// Merge builtins + module entries, dedupe by id (module wins so it
// can override the built-in for the same id), then sort by ``order``.
const navItems = computed(() => {
  const map = new Map()
  for (const item of builtinItems) map.set(item.id, item)
  for (const item of moduleEntries.value) map.set(item.id, item)
  return Array.from(map.values()).sort(
    (a, b) => (a.order ?? 100) - (b.order ?? 100),
  )
})

const isCollapsed = ref(false)
</script>

<template>
  <aside
    class="bg-gray-800 border-r border-gray-700 flex flex-col transition-all duration-300 z-10 shrink-0"
    :class="isCollapsed ? 'w-16' : 'w-64'"
  >
    <!-- Header & Toggle -->
    <div class="p-4 border-b border-gray-700 flex items-center h-16 shrink-0" :class="isCollapsed ? 'justify-center' : 'justify-between'">
      <h1 v-if="!isCollapsed" class="text-xl font-bold tracking-wider text-blue-400 whitespace-nowrap overflow-hidden">LinuxCNC</h1>

      <button
        @click="isCollapsed = !isCollapsed"
        class="text-gray-400 hover:text-white transition-colors focus:outline-none"
      >
        <!-- Hamburger Icon -->
        <svg v-if="isCollapsed" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path></svg>
        <!-- Chevron Left Icon -->
        <svg v-else class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path></svg>
      </button>
    </div>

    <!-- Navigation Links -->
    <nav class="flex-1 py-4 space-y-2 overflow-y-auto overflow-x-hidden">
      <button
        v-for="item in navItems"
        :key="item.id"
        @click="emit('navigate', item.id)"
        class="w-full flex items-center px-4 py-3 transition-colors outline-none"
        :class="[
          currentView === item.id
            ? 'bg-blue-600 text-white border-r-4 border-blue-400'
            : 'text-gray-400 hover:bg-gray-700 hover:text-gray-200 border-r-4 border-transparent',
          isCollapsed ? 'justify-center' : 'justify-start'
        ]"
        :title="isCollapsed ? item.label : ''"
      >
        <span v-html="item.icon"></span>
        <span v-if="!isCollapsed" class="ml-3 font-medium tracking-wide whitespace-nowrap">{{ item.label }}</span>
      </button>
    </nav>
  </aside>
</template>