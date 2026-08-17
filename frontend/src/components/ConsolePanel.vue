<script setup>
import { ref, watch, nextTick, computed, onMounted, onBeforeUnmount } from 'vue'
import { useConsoleStore, LOG_LEVELS } from '../stores/console'
import { ModulesMachineStateService } from '../../generated/api/services/ModulesMachineStateService'
import { filterAutocompleteCommands } from '../config/gcodes'
import { useMachineStore } from '../stores/machine'

const consoleStore = useConsoleStore()
const machineStore = useMachineStore()

const commandInput = ref('')
const messageContainer = ref(null)
const inputWrapper = ref(null)

// Command History
const commandHistory = ref([])
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

// Auto-scroll to bottom on new message
watch(() => consoleStore.messages, async () => {
  await nextTick()
  if (messageContainer.value) {
    messageContainer.value.scrollTop = messageContainer.value.scrollHeight
  }
}, { deep: true })

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
    consoleStore.error(`Error: ${e.message}`)
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

const selectSuggestion = (entry) => {
  if (!entry) return
  commandInput.value = entry.command
  showSuggestions.value = false
  suggestionIndex.value = -1
  // The user just chose a value — keep focus on the input so the
  // follow-up ``Enter`` submits the command without an extra click.
  const inputEl = inputWrapper.value?.querySelector('input')
  if (inputEl) inputEl.focus()
}

const moveSuggestion = (delta) => {
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

const onKeyDown = (event) => {
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
const handleDocumentMouseDown = (event) => {
  if (!inputWrapper.value) return
  if (inputWrapper.value.contains(event.target)) return
  showSuggestions.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', handleDocumentMouseDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentMouseDown)
})

// Styling for different message types
const getMessageClass = (type) => {
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
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-full">

    <!-- Header -->
    <div class="bg-gray-700/50 px-4 py-2 border-b border-gray-600 flex justify-between items-center gap-3">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm shrink-0">Terminal / Console</h2>

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

      <button @click="consoleStore.clearMessages()" class="text-xs text-gray-400 hover:text-white transition-colors shrink-0">Clear</button>
    </div>

    <!-- Message Area -->
    <div ref="messageContainer" class="flex-1 p-4 overflow-y-auto space-y-1 font-mono text-sm">
      <div v-if="consoleStore.filteredMessages.length === 0" class="text-gray-600 italic">
        <span v-if="consoleStore.messages.length === 0">Console ready...</span>
        <span v-else>No messages at the {{ filterLevel }} level.</span>
      </div>
      <div
        v-for="msg in consoleStore.filteredMessages"
        :key="msg.id"
        class="flex space-x-2"
      >
        <span class="text-gray-500 shrink-0">[{{ msg.timestamp }}]</span>
        <span :class="getMessageClass(msg.type)" class="break-all">{{ msg.text }}</span>
      </div>
    </div>

    <!-- Input Area -->
    <div class="p-3 bg-gray-900 border-t border-gray-700 mt-auto relative">
      <!-- Autocomplete menu — absolutely positioned so it floats
           above the input box. Anchored to the bottom of the input
           row via the negative ``bottom`` offset. -->
      <div
        v-if="showSuggestions && suggestions.length > 0"
        class="absolute left-3 right-3 bottom-full mb-1 bg-gray-800 border border-gray-600 rounded shadow-lg max-h-56 overflow-y-auto z-10"
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
        <button
          @click="submitCommand"
          class="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-semibold transition-colors"
        >
          SEND
        </button>
      </div>
    </div>
  </div>
</template>
