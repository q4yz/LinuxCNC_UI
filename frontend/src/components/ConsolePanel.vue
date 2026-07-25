<script setup>
import { ref, watch, nextTick } from 'vue'
import { useConsoleStore } from '../stores/console'
import { useMachineStore } from '../stores/machine'
import { ModulesMachineService } from '../../generated/api/services/ModulesMachineService'

const consoleStore = useConsoleStore()
const machineStore = useMachineStore()

const commandInput = ref('')
const messageContainer = ref(null)

// Command History
const commandHistory = ref([])
const historyIndex = ref(-1)

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
  consoleStore.addMessage(cmd, 'command')

  // Add to history
  commandHistory.value.push(cmd)
  historyIndex.value = commandHistory.value.length

  try {
    // Cannot send commands while in ESTOP
    if (machineStore.isEstop) {
       consoleStore.addMessage("Machine is in ESTOP. Command rejected.", 'error')
    } else {
       await ModulesMachineService.runMdiCommand({ command: cmd })
       consoleStore.addMessage(`Executed: ${cmd}`, 'success')
    }
  } catch (e) {
    consoleStore.addMessage(`Error: ${e.message}`, 'error')
  }

  commandInput.value = ''
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

// Styling for different message types
const getMessageClass = (type) => {
  switch(type) {
    case 'error': return 'text-red-400 font-semibold'
    case 'warning': return 'text-yellow-400'
    case 'success': return 'text-green-400'
    case 'command': return 'text-blue-300 font-bold'
    default: return 'text-gray-300'
  }
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-full">
    
    <!-- Header -->
    <div class="bg-gray-700/50 px-4 py-2 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Terminal / Console</h2>
      <button @click="consoleStore.clearMessages()" class="text-xs text-gray-400 hover:text-white transition-colors">Clear</button>
    </div>

    <!-- Message Area -->
    <div ref="messageContainer" class="flex-1 p-4 overflow-y-auto space-y-1 font-mono text-sm">
      <div v-if="consoleStore.messages.length === 0" class="text-gray-600 italic">Console ready...</div>
      <div 
        v-for="msg in consoleStore.messages" 
        :key="msg.id" 
        class="flex space-x-2"
      >
        <span class="text-gray-500 shrink-0">[{{ msg.timestamp }}]</span>
        <span :class="getMessageClass(msg.type)" class="break-all">{{ msg.text }}</span>
      </div>
    </div>

    <!-- Input Area -->
    <div class="p-3 bg-gray-900 border-t border-gray-700 flex items-center space-x-2 mt-auto">
      <span class="text-blue-500 font-bold font-mono">></span>
      <input 
        v-model="commandInput"
        @keyup.enter="submitCommand"
        @keydown.up.prevent="historyUp"
        @keydown.down.prevent="historyDown"
        type="text" 
        placeholder="Enter G-Code or MDI command..." 
        class="flex-1 bg-transparent text-gray-100 font-mono focus:outline-none placeholder-gray-600"
      >
      <button 
        @click="submitCommand"
        class="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-semibold transition-colors"
      >
        SEND
      </button>
    </div>
  </div>
</template>