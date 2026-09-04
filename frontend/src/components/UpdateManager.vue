<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine'
import { useConsoleStore } from '../stores/console'
import { SystemService } from '../../generated/api/services/SystemService'
import { MachineLifecycleFacade, type MachineStatus } from '../facades/machineLifecycleFacade'
import { BaseButton } from '../ui/index.ts'
import BaseCard from '../ui/BaseCard.vue'
import { openInEditor, EDITOR_SOURCES } from '../helpers/openInEditor'

const store = useMachineStore()
const consoleStore = useConsoleStore()
const { isUpdating } = storeToRefs(store)

const currentVersion = ref('loading...')
const latestVersion = ref('unknown')

// Machine lifecycle (system service :8001). "Start default machine"
// launches the persisted default machine's config/machine.ini —
// the same machine the offline card's Start button launches.
const machineStatus = ref<MachineStatus | null>(null)
const isStartingMachine = ref(false)
const isStoppingMachine = ref(false)

// The console log (logs/linuxcnc_console.log — tee'd stdout+stderr
// of the last LinuxCNC session) opens in the universal read-only
// editor, same as "Active Config" / "Compiled Output". "View log"
// opens it on demand; a start failure opens it automatically so the
// operator sees why without shell access.
function openConsoleLog() {
  void openInEditor({
    source: EDITOR_SOURCES.MACHINE_LOG,
    name: 'linuxcnc_console.log',
    readOnly: true,
  })
}

const fetchVersion = async () => {
  try {
    const res = await SystemService.getVersionInfo()
    // Prefer the simple `version` field (commit hash) if present
    currentVersion.value = res.version || res.current_version || 'unknown'
    latestVersion.value = res.latest_version || res.version || 'unknown'
    if (res.update_available) {
      consoleStore.info('Update available')
    }
  } catch (error) {
    consoleStore.error(`Failed to fetch version: ${error instanceof Error ? error.message : String(error)}`)
    currentVersion.value = 'error'
  }
}

const updateSystem = async () => {
  if (!confirm("Are you sure you want to update the system? The machine will stop and connection may be lost.")) {
    return
  }

  try {
    store.$patch({ isUpdating: true })
    consoleStore.warning("System update initiated. Connection may be lost temporarily...")
    await SystemService.triggerSystemUpdate()

    // We expect the websocket to drop or page to reload eventually,
    // but we can optionally reload after a timeout.
    setTimeout(() => {
      window.location.reload()
    }, 10000)
  } catch (error) {
    store.$patch({ isUpdating: false })
    consoleStore.error(`Update failed to start: ${error instanceof Error ? error.message : String(error)}`)
  }
}

async function refreshMachineStatus() {
  try {
    machineStatus.value = await MachineLifecycleFacade.getStatus()
  } catch {
    // Status line is informational only — absence renders the
    // "unknown" placeholder instead of an error row.
    machineStatus.value = null
  }
}

async function startDefaultMachine() {
  if (isStartingMachine.value) return
  isStartingMachine.value = true
  try {
    const status = await MachineLifecycleFacade.startMachine()
    machineStatus.value = status
    const name = status.default_machine ?? 'default machine'
    consoleStore.success(`Started ${name} (pid ${status.started_pid ?? '?'})`)
  } catch (error) {
    const status = (error as { status?: unknown } | null)?.status
    if (status === 409) {
      consoleStore.warning('LinuxCNC is already running')
    } else if (status === 404) {
      consoleStore.error('No default machine selected — pick one with "Set main" in the Machines explorer')
    } else {
      // Most likely a crash-on-launch (bad INI, realtime error, ...) —
      // the console log has the real reason, so pop it open directly
      // instead of leaving the operator to go find it.
      consoleStore.error(`Failed to start machine: ${error instanceof Error ? error.message : String(error)}`)
      openConsoleLog()
    }
  } finally {
    isStartingMachine.value = false
    void refreshMachineStatus()
  }
}

async function stopMachine() {
  if (isStoppingMachine.value) return
  isStoppingMachine.value = true
  try {
    const status = await MachineLifecycleFacade.stopMachine()
    machineStatus.value = status
    consoleStore.info('Machine stopped')
  } catch (error) {
    consoleStore.error(`Failed to stop machine: ${error instanceof Error ? error.message : String(error)}`)
  } finally {
    isStoppingMachine.value = false
    void refreshMachineStatus()
  }
}

onMounted(() => {
  fetchVersion()
  void refreshMachineStatus()
})
</script>

<template>
  <BaseCard title="⚙️ System Update">
    <div class="flex items-center justify-between  p-4">
      <div class="flex flex-col">
        <span class="text-gray-400 text-xs">Current Version</span>
        <span class="font-mono text-lg font-bold text-gray-200">{{ currentVersion }}</span>
        <span class="text-gray-400 text-xs">Latest</span>
        <span class="font-mono text-sm text-gray-400">{{ latestVersion }}</span>
      </div>

      <BaseButton variant="secondary" :loading="isUpdating" @click="updateSystem">
        <span class="mr-2">🔄</span> Update System
      </BaseButton>
    </div>

    <!--
      Machine session controls. Both buttons go through the
      always-up system service (:8001): start launches the persisted
      default machine's machines/<default>/config/machine.ini, stop
      is idempotent (SIGINT → SIGTERM → SIGKILL).
    -->
    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-gray-700 p-4">
      <div class="flex flex-col">
        <span class="text-gray-400 text-xs">Default Machine</span>
        <span
          v-if="machineStatus?.default_machine"
          class="flex items-center gap-2 font-mono text-sm font-bold text-gray-200"
          data-testid="machine-default-name"
        >
          {{ machineStatus.default_machine }}
          <span
            class="rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-widest"
            :class="machineStatus.running
              ? 'border-emerald-700 text-emerald-300'
              : 'border-slate-600 text-slate-400'"
          >
            {{ machineStatus.running ? 'running' : 'stopped' }}
          </span>
        </span>
        <span v-else class="font-mono text-sm text-gray-500" data-testid="machine-default-name">
          none selected — use "Set main" in the Machines explorer
        </span>
      </div>

      <div class="flex gap-2">
        <BaseButton
          variant="success"
          :loading="isStartingMachine"
          :disabled="isStoppingMachine"
          data-testid="machine-start-default"
          @click="startDefaultMachine"
        >
          ▶ Start default machine
        </BaseButton>
        <BaseButton
          variant="danger"
          :loading="isStoppingMachine"
          :disabled="isStartingMachine"
          data-testid="machine-stop"
          @click="stopMachine"
        >
          ⏹ Stop machine
        </BaseButton>
        <BaseButton
          variant="secondary"
          data-testid="machine-view-log"
          @click="openConsoleLog"
        >
          📜 View log
        </BaseButton>
      </div>
    </div>

    <!-- Fullscreen Overlay using Teleport -->
    <Teleport to="body">
      <div
        v-if="isUpdating"
        class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/90 backdrop-blur-sm"
      >
        <div class="flex flex-col items-center p-8 bg-gray-800 border border-gray-700 rounded-xl shadow-2xl max-w-md w-full text-center">
          <div class="w-16 h-16 mb-6 border-4 border-yellow-500 border-t-transparent rounded-full animate-spin"></div>
          <h2 class="text-2xl font-bold text-white mb-2 tracking-wide">UPDATING SYSTEM</h2>
          <p class="text-gray-400">Please wait while the system pulls the latest updates and reinstalls dependencies. The page will reload automatically.</p>
        </div>
      </div>
    </Teleport>
  </BaseCard>
</template>
