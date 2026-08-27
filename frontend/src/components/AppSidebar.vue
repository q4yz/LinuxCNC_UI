<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from "../ui/index.ts";

const route = useRoute()
const router = useRouter()

// ``activeId`` is the route's name (Vue Router owns the active view).
// The App shell renders the matching view for every sidebar name;
// built-in entries and per-domain entries are declared inline here
// (no registry — modules are hard dependencies in this build).
const activeId = computed(() => route.name || 'dashboard')

function navigate(view) {
  router.push({ name: view })
}

const builtinItems = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', order: 1 },
  { id: 'programs', label: 'G-Code Files', icon: 'programs', order: 2 },
  { id: 'camera', label: 'Camera', icon: 'camera', order: 3 },
  { id: 'machineconfig', label: 'Machine Config', icon: 'machineconfig', order: 4 },
  { id: 'settings', label: 'Settings', icon: 'settings', order: 5 },
];

const navItems = computed(() =>
  [...builtinItems].sort((a, b) => (a.order ?? 100) - (b.order ?? 100)),
);

const isCollapsed = ref(false);
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
        @click="navigate(item.id)"
        class="w-full flex items-center px-4 py-3 transition-colors outline-none"
        :class="[
          activeId === item.id
            ? 'bg-blue-600 text-white border-r-4 border-blue-400'
            : 'text-gray-400 hover:bg-gray-700 hover:text-gray-200 border-r-4 border-transparent',
          isCollapsed ? 'justify-center' : 'justify-start'
        ]"
        :title="isCollapsed ? item.label : ''"
      >
        <!-- Render the shared Icon component -->
        <Icon :name="item.icon" size="h-6 w-6" />

        <!-- Render the label (hidden when sidebar is collapsed) -->
        <span v-if="!isCollapsed" class="ml-3 font-medium tracking-wide whitespace-nowrap">{{ item.label }}</span>
      </button>
    </nav>
  </aside>
</template>