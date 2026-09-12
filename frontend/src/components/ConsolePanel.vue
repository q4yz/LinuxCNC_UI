<script setup lang="ts">
import { ref, watch, nextTick, computed, onMounted, onBeforeUnmount } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { useConsoleStore, LOG_LEVELS } from '../stores/console'
import { ModulesMachineStateService } from '../../generated/api/services/ModulesMachineStateService'
import { filterAutocompleteCommands } from '../config/gcodes'
import { useMachineStore } from '../stores/machine'
import { BaseButton } from '../ui/index.ts'
import BaseCard from '../ui/BaseCard.vue'

const consoleStore = useConsoleStore()
const machineStore = useMachineStore()

const commandInput = ref('')
const messageContainer = ref<HTMLElement | null>(null)
const inputWrapper = ref<HTMLElement | null>(null)

// Command History
const commandHistory = ref<string[]>([])
const historyIndex = ref(-1)

// ----------------------------------------------------------------- //
// Autocomplete state                                                //
// ----------------------------------------------------------------- //
//
// The suggestion list is a ``computed`` derived from the current
// input. The menu is hidden when the list is empty, the input is
// empty, or the input has lost focus. Keyboard navigation uses
// ``suggestionIndex`` (negative = no selection) so the highlighter
// always corresponds to the highlighted row.
const showSuggestions = ref(false)
const suggestionIndex = ref(-1)
const suggestions = computed(() => filterAutocompleteCommands(commandInput.value))

watch(suggestions, () => {
  // Reset the highlight whenever the filtered list changes shape
  // so the cursor can never end up on an out-of-range row.
  suggestionIndex.value = suggestions.value.length > 0 ? 0 : -1
})

// Read the currently selected filter level directly from the
// store so the chips react to external changes (e.g. tests).
const filterLevel = computed({
  get: () => consoleStore.filterLevel,
  set: (value) => consoleStore.setFilterLevel(value),
})

// Tailwind classes for each level — centralised here so the
// chip row and the message row stay in sync.
const levelChipStyles = {
  all: 'bg-gray-600 text-white',
  debug: 'bg-gray-500 text-white',
  info: 'bg-blue-600/80 text-white',
  warning: 'bg-yellow-600/80 text-black',
  error: 'bg-red-600/80 text-white',

}

const levelChipInactive = 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'

// ----------------------------------------------------------------- //
// Virtualized message list                                          //
// ----------------------------------------------------------------- //
//
// A long-running session can accumulate thousands of console lines;
// rendering every one of them as a real DOM node (as a plain
// ``v-for`` used to) means the list keeps costing more to lay out
// and paint the longer the session runs. ``@tanstack/vue-virtual``
// only mounts the rows currently in (or near) the viewport, so the
// render cost stays flat regardless of how large ``messages`` grows
// — the console effectively gets infinite scroll for free. Row
// height varies with wrapped text, so sizing is measured live via
// ``measureElement`` rather than assumed fixed.
const rowVirtualizer = useVirtualizer(computed(() => ({
  count: consoleStore.filteredMessages.length,
  getScrollElement: () => messageContainer.value,
  estimateSize: () => 20,
  overscan: 12,
})))

// Auto-scroll to bottom on new message. Watching ``.length`` (not
// ``messages`` with ``{ deep: true }``) means this only re-runs when
// a row is actually added/removed instead of walking every message
// object's fields on every mutation.
watch(() => consoleStore.filteredMessages.length, async (length) => {
  if (length === 0) return
  await nextTick()
  rowVirtualizer.value.scrollToIndex(length - 1, { align: 'end' })
})

const submitCommand = async () => {
  const cmd = commandInput.value.trim()
  if (!cmd) return

  // Echo command to console
  consoleStore.command(cmd)

  // Add to history
  commandHistory.value.push(cmd)
  historyIndex.value = commandHistory.value.length

  try {
    // Cannot send commands while in ESTOP
    if (machineStore.isEstop) {
       consoleStore.error("Machine is in ESTOP. Command rejected.")
    } else {
       await ModulesMachineStateService.runMdiCommand({ command: cmd })
       consoleStore.success(`Executed: ${cmd}`)
    }
  } catch (e) {
    consoleStore.error(`Error: ${e instanceof Error ? e.message : String(e)}`)
  }

  commandInput.value = ''
  showSuggestions.value = false
}

const onInput = () => {
  // Open the menu whenever the user starts typing. The ``computed``
  // ``suggestions`` returns ``[]`` for an empty input, which is
  // already what the template uses to hide the box.
  showSuggestions.value = commandInput.value.trim().length > 0
  suggestionIndex.value = suggestions.value.length > 0 ? 0 : -1
}

const onFocus = () => {
  if (commandInput.value.trim().length > 0) {
    showSuggestions.value = true
  }
}

const onBlur = () => {
  // Defer the close so a click on a suggestion row can still
  // resolve and fire ``selectSuggestion`` before the menu hides.
  setTimeout(() => {
    showSuggestions.value = false
  }, 120)
}

interface SuggestionEntry {
  command: string;
}

const selectSuggestion = (entry: SuggestionEntry | null | undefined) => {
  if (!entry) return
  commandInput.value = entry.command
  showSuggestions.value = false
  suggestionIndex.value = -1
  // The user just chose a value — keep focus on the input so the
  // follow-up ``Enter`` submits the command without an extra click.
  const inputEl = inputWrapper.value?.querySelector('input')
  if (inputEl) inputEl.focus()
}

const moveSuggestion = (delta: number) => {
  if (!suggestions.value.length) return
  const next = suggestionIndex.value + delta
  if (next < 0) {
    suggestionIndex.value = suggestions.value.length - 1
  } else if (next >= suggestions.value.length) {
    suggestionIndex.value = 0
  } else {
    suggestionIndex.value = next
  }
}

const onKeyDown = (event: KeyboardEvent) => {
  // The menu is only useful while it is visible.
  if (!showSuggestions.value || suggestions.value.length === 0) {
    // ``Tab`` is otherwise captured by the browser for focus
    // traversal; when there are no suggestions we let it bubble
    // through so the rest of the page keeps working.
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveSuggestion(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveSuggestion(-1)
  } else if (event.key === 'Tab' || event.key === 'Enter') {
    // Hijack ``Tab`` to autocomplete while the menu is open.
    // ``Enter`` is handled by the input's ``@keyup.enter`` binding
    // — we only intercept it here when the menu is visible so the
    // autocomplete beats the submit when both are eligible.
    event.preventDefault()
    const entry = suggestions.value[suggestionIndex.value]
    if (entry) {
      selectSuggestion(entry)
    }
  } else if (event.key === 'Escape') {
    showSuggestions.value = false
  }
}

const historyUp = () => {
  if (commandHistory.value.length === 0) return
  if (historyIndex.value > 0) {
    historyIndex.value--
    commandInput.value = commandHistory.value[historyIndex.value]
  }
}

const historyDown = () => {
  if (commandHistory.value.length === 0) return
  if (historyIndex.value < commandHistory.value.length - 1) {
    historyIndex.value++
    commandInput.value = commandHistory.value[historyIndex.value]
  } else {
    historyIndex.value = commandHistory.value.length
    commandInput.value = ''
  }
}

// ----------------------------------------------------------------- //
// Outside-click handler                                              //
// ----------------------------------------------------------------- //
//
// The ``@blur`` on the input covers ``Tab``-driven focus loss, but
// a click elsewhere in the document needs a window-level listener
// to close the menu. The component owns the listener so it is
// removed in ``onBeforeUnmount`` and never leaks across reloads.
const handleDocumentMouseDown = (event: MouseEvent) => {
  if (!inputWrapper.value) return
  if (inputWrapper.value.contains(event.target as Node)) return
  showSuggestions.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', handleDocumentMouseDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentMouseDown)
})

// Styling for different message types
const getMessageClass = (type: string) => {
  switch(type) {
    case 'error': return 'text-red-400 font-semibold'
    case 'warning': return 'text-yellow-400'
    case 'success': return 'text-green-400'
    case 'command': return 'text-blue-300 font-bold'
    case 'debug': return 'text-gray-500 italic'
    default: return 'text-gray-300'
  }
}
</script>

<template>
  <BaseCard title="Terminal / Console" class="h-full flex flex-col overflow-hidden">
    <template #header-actions>
      <!-- Log level filter chips -->
      <div class="flex items-center gap-1 flex-wrap" data-test="console-level-chips">
        <button
          v-for="level in LOG_LEVELS"
          :key="level"
          type="button"
          @click="filterLevel = level"
          :class="[
            'px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider transition-colors',
            filterLevel === level ? levelChipStyles[level] : levelChipInactive
          ]"
          :data-test="`console-level-${level}`"
          :aria-pressed="filterLevel === level"
        >
          {{ level }}
        </button>
      </div>

      <BaseButton variant="ghost" size="sm" class="shrink-0" @click="consoleStore.clearMessages()">Clear</BaseButton>
    </template>

    <div class="flex flex-col h-full">
      <!-- Message Area — virtualized: only the rows near the viewport
           are ever mounted, so the DOM cost stays flat no matter how
           long the session's console history grows. -->
      <div ref="messageContainer" class="flex-1 min-h-0 p-4 overflow-y-auto font-mono text-sm">
        <div v-if="consoleStore.filteredMessages.length === 0" class="text-gray-600 italic">
          <span v-if="consoleStore.messages.length === 0">Console ready...</span>
          <span v-else>No messages at the {{ filterLevel }} level.</span>
        </div>
        <div v-else :style="{ height: `${rowVirtualizer.getTotalSize()}px`, position: 'relative', width: '100%' }">
          <div
            v-for="virtualRow in rowVirtualizer.getVirtualItems()"
            :key="virtualRow.index"
            :ref="(el) => rowVirtualizer.measureElement(el as Element)"
            :data-index="virtualRow.index"
            class="flex space-x-2 pb-1"
            :style="{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${virtualRow.start}px)` }"
          >
            <span class="text-gray-500 shrink-0">[{{ consoleStore.filteredMessages[virtualRow.index].timestamp }}]</span>
            <span :class="getMessageClass(consoleStore.filteredMessages[virtualRow.index].type)" class="break-all">{{ consoleStore.filteredMessages[virtualRow.index].text }}</span>
          </div>
        </div>
      </div>

      <!-- Input Area -->
      <div class="p-3 bg-gray-900 border-t border-gray-700 relative">
        <!-- Autocomplete menu — absolutely positioned so it floats
             above the input box. Anchored to the bottom of the input
             row via the negative ``bottom`` offset. -->
        <div
          v-if="showSuggestions && suggestions.length > 0"
          class="absolute left-3 right-3 bottom-full mb-1 bg-gray-800 border border-gray-600 rounded max-h-56 overflow-y-auto z-10"
          data-test="console-suggestions"
        >
          <div
            v-for="(entry, idx) in suggestions"
            :key="entry.label"
            @mousedown.prevent="selectSuggestion(entry)"
            @mouseenter="suggestionIndex = idx"
            :class="[
              'px-3 py-1.5 cursor-pointer font-mono text-sm flex justify-between items-center',
              suggestionIndex === idx ? 'bg-blue-600/40 text-white' : 'text-gray-200 hover:bg-gray-700'
            ]"
            :data-test="`console-suggestion-${entry.label}`"
          >
            <span class="font-semibold">{{ entry.label }}</span>
            <span class="text-gray-400 text-xs ml-3 truncate">{{ entry.description }}</span>
          </div>
        </div>

        <div ref="inputWrapper" class="flex items-center space-x-2">
          <span class="text-blue-500 font-bold font-mono">></span>
          <input
            v-model="commandInput"
            @input="onInput"
            @focus="onFocus"
            @blur="onBlur"
            @keydown="onKeyDown"
            @keyup.enter="submitCommand"
            @keydown.up.prevent="historyUp"
            @keydown.down.prevent="historyDown"
            type="text"
            placeholder="Enter G-Code or MDI command..."
            class="flex-1 bg-transparent text-gray-100 font-mono focus:outline-none placeholder-gray-600"
            autocomplete="off"
            spellcheck="false"
            data-test="console-input"
          >
          <BaseButton variant="primary" size="sm" @click="submitCommand">
            SEND
          </BaseButton>
        </div>
      </div>
    </div>
  </BaseCard>
</template>
