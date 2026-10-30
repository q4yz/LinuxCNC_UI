<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useConsoleStore } from '../stores/console'
import { useSystemUpdateStore } from '../stores/systemUpdate'
import { systemFacade } from '../facades/systemFacade'
import { CommandResult } from '../entities/common/CommandResult'
import type { UpdateMode } from '../entities/system'
import { MachineLifecycleFacade, type MachineStatus } from '../facades/machineLifecycleFacade'
import { BaseButton, Icon } from '../ui/index.ts'
import BaseCard from '../ui/BaseCard.vue'
import { openInEditor, EDITOR_SOURCES } from '../helpers/openInEditor'

const consoleStore = useConsoleStore()
// The update itself is tracked app-wide (stores/systemUpdate.ts +
// UpdateOverlay.vue in App.vue) so it survives navigation and reloads.
const updateStore = useSystemUpdateStore()
const { isRunning: isUpdating } = storeToRefs(updateStore)

const currentVersion = ref('loading...')
// Tag of the latest GitHub release; '' when none exists or GitHub is unreachable.
const latestRelease = ref('')
const releaseAvailable = ref(false)

// Machine lifecycle (system service :8001). "Start default machine"
// launches the persisted default machine's config/machine.ini —
// the same machine the offline card's Start button launches.
const machineStatus = ref<MachineStatus | null>(null)
const isStartingMachine = ref(false)
const isStoppingMachine = ref(false)

// Two logs, two buttons, each in the universal read-only editor:
// "LinuxCNC log" is LinuxCNC's own output (logs/linuxcnc_console.log
// plus ~/linuxcnc_print.txt / ~/linuxcnc_debug.txt) — a start failure
// opens it automatically; "UI log" is this UI's own backends
// (logs/ui_system.log, logs/ui_machine.log).
function openConsoleLog() {
  void openInEditor({
    source: EDITOR_SOURCES.MACHINE_LOG,
    name: 'linuxcnc_console.log',
    readOnly: true,
  })
}
function openUiLog() {
  void openInEditor({
    source: EDITOR_SOURCES.UI_LOG,
    name: 'linuxcnc_ui.log',
    readOnly: true,
  })
}

const fetchVersion = async () => {
  const result = await systemFacade.fetchVersion()
  if (result instanceof CommandResult) {
    consoleStore.error(`Failed to fetch version: ${result.failureReason}`)
    currentVersion.value = 'error'
    return
  }
  currentVersion.value = result.version || 'unknown'
  latestRelease.value = result.latestVersion
  releaseAvailable.value = result.isUpdatable
  if (result.isUpdatable) {
    consoleStore.info(`Release ${result.latestVersion} available`)
  }
}

// Two update paths (scripts/update.sh --mode):
//   commit  — git pull + frontend built on this board. For testing;
//             vite needs more RAM than 1 GB boards (CB1) have.
//   release — the latest GitHub release with the frontend CI prebuilt;
//             nothing is compiled here.
const UPDATE_CONFIRM: Record<UpdateMode, string> = {
  commit:
    'Build the newest commit on this machine?\n\nFor testing: the interface is compiled here, which needs ' +
    'about 2 GB of RAM and several minutes. The machine stops and the connection may be lost.',
  release:
    'Install the latest release?\n\nThe prebuilt interface is downloaded — nothing is compiled here. ' +
    'The machine stops and the connection may be lost.',
}

const updateSystem = async (mode: UpdateMode) => {
  if (!confirm(UPDATE_CONFIRM[mode])) return

  // Overlay, progress, reload and the finish / failure notification
  // follow the status the update script writes — no fixed timer.
  await updateStore.start(mode)
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
    // e.g. 409: LinuxCNC was started from another process — the
    // backend's reason says so; keep it until the operator closes it.
    consoleStore.error(`Failed to stop machine: ${error instanceof Error ? error.message : String(error)}`, {
      popup: true,
      title: 'Stop machine',
      lifetime: null,
    })
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
  <BaseCard title="System Update" icon="settings">
    <div class="flex items-center justify-between  p-4">
      <div class="flex flex-col">
        <span class="text-gray-400 text-xs">Current Version</span>
        <span class="font-mono text-lg font-bold text-gray-200">{{ currentVersion }}</span>
        <span class="text-gray-400 text-xs">Latest Release</span>
        <span class="flex items-center gap-2 font-mono text-sm text-gray-400" data-testid="latest-release">
          {{ latestRelease || 'none found' }}
          <span
            v-if="releaseAvailable"
            class="rounded border border-emerald-700 px-1.5 py-0.5 text-[10px] uppercase tracking-widest text-emerald-300"
          >
            new
          </span>
        </span>
      </div>

      <div class="flex flex-wrap justify-end gap-2">
        <BaseButton
          variant="secondary"
          :disabled="isUpdating"
          title="git pull + build the interface on this machine (testing; needs ~2 GB RAM)"
          data-testid="update-commit"
          @click="updateSystem('commit')"
        >
          <Icon name="refresh" class="mr-2" /> Build newest commit
        </BaseButton>
        <BaseButton
          :variant="releaseAvailable ? 'success' : 'secondary'"
          :disabled="isUpdating || !latestRelease"
          :title="latestRelease ? `Download release ${latestRelease} (prebuilt, nothing compiled here)` : 'No release found on GitHub'"
          data-testid="update-release"
          @click="updateSystem('release')"
        >
          <Icon name="download" class="mr-2" /> Install latest release
        </BaseButton>
      </div>
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
          <Icon name="stop" class="mr-1" /> Stop machine
        </BaseButton>
        <BaseButton
          variant="secondary"
          data-testid="machine-view-log"
          @click="openConsoleLog"
        >
          <Icon name="log" class="mr-1" /> LinuxCNC log
        </BaseButton>
        <BaseButton
          variant="secondary"
          data-testid="machine-view-ui-log"
          @click="openUiLog"
        >
          <Icon name="log" class="mr-1" /> UI log
        </BaseButton>
      </div>
    </div>

  </BaseCard>
</template>
