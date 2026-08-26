<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

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

// Built-in entries are always present (they back the existing static
// sidebar). Per-domain entries (camera, machineconfig) are declared
// inline below; removing one is a build failure rather than a silent
// gap. ``order`` controls display weight — built-ins default to 100
// so a domain with ``order: 50`` floats above the built-ins.
const cameraIcon =
  '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" ' +
  'd="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />' +
  '</svg>';

const machineconfigIcon =
  '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" ' +
  'd="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z">' +
  '</path>' +
  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" ' +
  'd="M15 12a3 3 0 11-6 0 3 3 0 016 0z">' +
  '</path>' +
  '</svg>';

const builtinItems = [
  { id: 'dashboard', label: 'Dashboard', icon: '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>', order: 100 },
  { id: 'programs', label: 'G-Code Files', icon: '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>', order: 100 },
  { id: 'camera', label: 'Camera', icon: cameraIcon, order: 50 },
  { id: 'machineconfig', label: 'Machine Config', icon: machineconfigIcon, order: 80 },
  { id: 'settings', label: 'Settings', icon: '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>', order: 200 },
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
        <span v-html="item.icon"></span>
        <span v-if="!isCollapsed" class="ml-3 font-medium tracking-wide whitespace-nowrap">{{ item.label }}</span>
      </button>
    </nav>
  </aside>
</template>