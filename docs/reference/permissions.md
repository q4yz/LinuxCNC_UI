# Permissions

<!-- Generated from backend/common/core/permissions.py by
     permission_table_markdown(); edit that module, not this file. -->

Every route of both backends needs one permission; a role allows it,
allows it after the operator confirms (`confirm`), or refuses it (`-`).
For now every web user is **admin** (there are no logins yet).

## Roles

| Permission | What | admin | operator | viewer | agent |
|---|---|---|---|---|---|
| `machine.read` | machine state, positions, temperatures, I/O, progress | yes | yes | yes | yes |
| `camera.view` | camera images | yes | yes | yes | yes |
| `hal.read` | HAL pins, HAL editor, scope | yes | yes | yes | yes |
| `files.read` | G-code programs | yes | yes | yes | yes |
| `config.read` | profiles, machine files, M-codes, LinuxCNC log | yes | yes | yes | yes |
| `macros.read` | macros | yes | yes | yes | yes |
| `settings.read` | UI settings | yes | yes | yes | yes |
| `system.read` | version, releases, update status | yes | yes | yes | yes |
| `machine.estop` | engage the E-stop | yes | yes | yes | yes |
| `machine.power` | E-stop reset, machine on / off, mode | yes | yes | - | confirm |
| `machine.motion` | homing, MDI | yes | yes | - | confirm |
| `program.run` | load, run, pause, resume, stop a program | yes | yes | - | confirm |
| `machine.tune` | live Z offset, flow, speed, objects, mesh on / off | yes | yes | - | confirm |
| `heaters.control` | heater targets, extruder, spindle | yes | yes | - | confirm |
| `outputs.control` | fans, output pins, LEDs | yes | yes | - | confirm |
| `macros.run` | run a macro | yes | yes | - | confirm |
| `calibration.run` | calibrations, bed mesh probing, Z tilt | yes | yes | - | confirm |
| `files.write` | upload, edit, move, delete programs | yes | yes | - | confirm |
| `calibration.manage` | calibration reminders, reset to profile values | yes | yes | - | confirm |
| `bedmesh.manage` | save, delete, activate meshes | yes | yes | - | confirm |
| `settings.write` | change UI settings | yes | yes | - | - |
| `macros.write` | edit macros | yes | - | - | - |
| `session.control` | start, stop, switch LinuxCNC | yes | yes | - | - |
| `hal.write` | save the HAL editor layout | yes | - | - | - |
| `config.write` | profiles, machine generation, board upload, MCU reset | yes | - | - | - |
| `system.update` | update the software | yes | - | - | - |
| `users.manage` | users and roles | yes | - | - | - |
| `agent.approve` | approve or deny the assistant's actions | yes | yes | - | - |
| `agent.chat` | chat with the in-app assistant | yes | yes | - | - |

## Routes: machine backend

| Method | Path | Permission | agent |
|---|---|---|---|
| PUT | `/api/v1/calibration/{calibration_id}/reminder` | `calibration.manage` | confirm |
| DELETE | `/api/v1/calibration/{calibration_id}/values` | `calibration.manage` | confirm |
| POST | `/api/v1/bedmesh/calibrate` | `calibration.run` | confirm |
| POST | `/api/v1/calibration/{calibration_id}/result` | `calibration.run` | confirm |
| POST | `/api/v1/calibration/{calibration_id}/start` | `calibration.run` | confirm |
| POST | `/api/v1/ztilt/adjust` | `calibration.run` | confirm |
| GET | `/api/v1/modules/camera/devices` | `camera.view` | yes |
| GET | `/api/v1/modules/camera/status` | `camera.view` | yes |
| GET | `/api/v1/modules/camera/stream` | `camera.view` | yes |
| GET | `/api/v1/modules/camera/stream/diagnostic` | `camera.view` | yes |
| GET | `/api/v1/modules/camera/usb` | `camera.view` | yes |
| POST | `/api/v1/modules/mcu/reset` | `config.write` | - |
| POST | `/api/v1/modules/program/parse` | `config.write` | - |
| GET | `/api/v1/hal/layout` | `hal.read` | yes |
| GET | `/api/v1/hal/pins` | `hal.read` | yes |
| POST | `/api/v1/hal/pins/values` | `hal.read` | yes |
| WS | `/ws/hal-scope` | `hal.read` | yes |
| PUT | `/api/v1/hal/layout` | `hal.write` | - |
| POST | `/api/v1/modules/temperature/sensors/{name}/target` | `heaters.control` | confirm |
| POST | `/api/v1/modules/tools/extruder` | `heaters.control` | confirm |
| POST | `/api/v1/modules/tools/spindle` | `heaters.control` | confirm |
| POST | `/api/v1/modules/tools/tools/{tool_id}/target` | `heaters.control` | confirm |
| POST | `/api/v1/modules/machine_state/estop/activate` | `machine.estop` | yes |
| POST | `/api/v1/modules/axis/home` | `machine.motion` | confirm |
| POST | `/api/v1/modules/machine_state/mdi` | `machine.motion` | confirm |
| POST | `/api/v1/modules/machine_state/mode` | `machine.power` | confirm |
| POST | `/api/v1/modules/machine_state/state` | `machine.power` | confirm |
| GET | `/` | `machine.read` | yes |
| GET | `/api/v1/base-thread/snapshot` | `machine.read` | yes |
| GET | `/api/v1/bedmesh/calibrate` | `machine.read` | yes |
| GET | `/api/v1/bedmesh/enable` | `machine.read` | yes |
| GET | `/api/v1/calibration` | `machine.read` | yes |
| GET | `/api/v1/health` | `machine.read` | yes |
| GET | `/api/v1/leds` | `machine.read` | yes |
| GET | `/api/v1/modules/io` | `machine.read` | yes |
| GET | `/api/v1/modules/machine_state/state` | `machine.read` | yes |
| GET | `/api/v1/modules/tools/spindle/{tool_id}` | `machine.read` | yes |
| GET | `/api/v1/print-tuning` | `machine.read` | yes |
| GET | `/api/v1/ztilt/status` | `machine.read` | yes |
| GET | `/ws/_schema/telemetry` | `machine.read` | yes |
| WS | `/ws/telemetry` | `machine.read` | yes |
| PUT | `/api/v1/bedmesh/enable` | `machine.tune` | confirm |
| POST | `/api/v1/modules/axis/settings` | `machine.tune` | confirm |
| PUT | `/api/v1/print-tuning` | `machine.tune` | confirm |
| PUT | `/api/v1/print-tuning/objects/{index}` | `machine.tune` | confirm |
| POST | `/api/v1/modules/macros/{name}/start` | `macros.run` | confirm |
| PUT | `/api/v1/leds/{led_id}` | `outputs.control` | confirm |
| PUT | `/api/v1/modules/io/{pin_id}` | `outputs.control` | confirm |
| POST | `/api/v1/modules/program/load` | `program.run` | confirm |
| POST | `/api/v1/modules/program/pause` | `program.run` | confirm |
| POST | `/api/v1/modules/program/pause_inspect` | `program.run` | confirm |
| POST | `/api/v1/modules/program/resume` | `program.run` | confirm |
| POST | `/api/v1/modules/program/run` | `program.run` | confirm |
| POST | `/api/v1/modules/program/stop` | `program.run` | confirm |
| POST | `/api/v1/modules/program/unload` | `program.run` | confirm |

## Routes: system backend

| Method | Path | Permission | agent |
|---|---|---|---|
| GET | `/api/v1/agent/confirmations` | `agent.approve` | - |
| POST | `/api/v1/agent/confirmations/{confirmation_id}/approve` | `agent.approve` | - |
| POST | `/api/v1/agent/confirmations/{confirmation_id}/deny` | `agent.approve` | - |
| POST | `/api/v1/agent/chat` | `agent.chat` | - |
| DELETE | `/api/v1/agent/chat/{conversation_id}` | `agent.chat` | - |
| GET | `/api/v1/agent/chat/{conversation_id}` | `agent.chat` | - |
| POST | `/api/v1/agent/chat/{conversation_id}/stop` | `agent.chat` | - |
| POST | `/api/v1/modules/bedmesh/meshes` | `bedmesh.manage` | confirm |
| DELETE | `/api/v1/modules/bedmesh/meshes/{name}` | `bedmesh.manage` | confirm |
| PUT | `/api/v1/modules/bedmesh/meshes/{name}` | `bedmesh.manage` | confirm |
| POST | `/api/v1/modules/bedmesh/meshes/{name}/activate` | `bedmesh.manage` | confirm |
| GET | `/api/v1/modules/machineconfig/m-codes/content` | `config.read` | yes |
| GET | `/api/v1/modules/machineconfig/m-codes/list` | `config.read` | yes |
| GET | `/api/v1/modules/machineconfig/machines/content` | `config.read` | yes |
| GET | `/api/v1/modules/machineconfig/machines/tree` | `config.read` | yes |
| GET | `/api/v1/modules/machineconfig/profiles/content` | `config.read` | yes |
| GET | `/api/v1/modules/machineconfig/profiles/tree` | `config.read` | yes |
| GET | `/api/v1/system/machine/log` | `config.read` | yes |
| PUT | `/api/v1/modules/machineconfig/m-codes/content` | `config.write` | - |
| DELETE | `/api/v1/modules/machineconfig/m-codes/{name}` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/machines/board-upload` | `config.write` | - |
| PUT | `/api/v1/modules/machineconfig/machines/content` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/machines/copy` | `config.write` | - |
| DELETE | `/api/v1/modules/machineconfig/machines/entry` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/machines/file` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/machines/folder` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/machines/generate` | `config.write` | - |
| PUT | `/api/v1/modules/machineconfig/machines/rename` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/machines/upload` | `config.write` | - |
| PUT | `/api/v1/modules/machineconfig/profiles/content` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/profiles/copy` | `config.write` | - |
| DELETE | `/api/v1/modules/machineconfig/profiles/entry` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/profiles/file` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/profiles/folder` | `config.write` | - |
| PUT | `/api/v1/modules/machineconfig/profiles/rename` | `config.write` | - |
| POST | `/api/v1/modules/machineconfig/profiles/upload` | `config.write` | - |
| POST | `/api/v1/system/machine/default` | `config.write` | - |
| GET | `/api/v1/programs` | `files.read` | yes |
| GET | `/api/v1/programs/content/{filename:path}` | `files.read` | yes |
| GET | `/api/v1/programs/thumbnail/{filename:path}` | `files.read` | yes |
| POST | `/api/files/local` | `files.write` | confirm |
| PUT | `/api/v1/programs/content/{filename:path}` | `files.write` | confirm |
| POST | `/api/v1/programs/copy` | `files.write` | confirm |
| POST | `/api/v1/programs/folder` | `files.write` | confirm |
| PUT | `/api/v1/programs/rename` | `files.write` | confirm |
| POST | `/api/v1/programs/upload` | `files.write` | confirm |
| DELETE | `/api/v1/programs/{filename:path}` | `files.write` | confirm |
| GET | `/api/connection` | `machine.read` | yes |
| GET | `/api/job` | `machine.read` | yes |
| GET | `/api/printer` | `machine.read` | yes |
| GET | `/api/v1/modules/bedmesh/defaults` | `machine.read` | yes |
| GET | `/api/v1/modules/bedmesh/meshes` | `machine.read` | yes |
| GET | `/api/v1/modules/bedmesh/meshes/{name}` | `machine.read` | yes |
| GET | `/api/v1/system/machine` | `machine.read` | yes |
| GET | `/api/v1/modules/macros` | `macros.read` | yes |
| GET | `/api/v1/modules/macros/{name}` | `macros.read` | yes |
| GET | `/api/v1/modules/macros/{name}/content` | `macros.read` | yes |
| DELETE | `/api/v1/modules/macros/{name}` | `macros.write` | - |
| PUT | `/api/v1/modules/macros/{name}` | `macros.write` | - |
| PUT | `/api/v1/modules/macros/{name}/content` | `macros.write` | - |
| POST | `/api/v1/system/machine/start` | `session.control` | - |
| POST | `/api/v1/system/machine/stop` | `session.control` | - |
| POST | `/api/v1/system/machine/switch` | `session.control` | - |
| GET | `/api/v1/agent/config` | `settings.read` | yes |
| GET | `/api/v1/agent/status` | `settings.read` | yes |
| GET | `/api/v1/settings` | `settings.read` | yes |
| GET | `/api/v1/settings/{key}` | `settings.read` | yes |
| PUT | `/api/v1/agent/config` | `settings.write` | - |
| DELETE | `/api/v1/settings/{key}` | `settings.write` | - |
| PUT | `/api/v1/settings/{key}` | `settings.write` | - |
| GET | `/` | `system.read` | yes |
| POST | `/api/login` | `system.read` | yes |
| GET | `/api/printerprofiles` | `system.read` | yes |
| GET | `/api/server` | `system.read` | yes |
| GET | `/api/settings` | `system.read` | yes |
| GET | `/api/v1/system/releases` | `system.read` | yes |
| GET | `/api/v1/system/update/status` | `system.read` | yes |
| GET | `/api/v1/system/version` | `system.read` | yes |
| GET | `/api/version` | `system.read` | yes |
| POST | `/api/v1/system/update` | `system.update` | - |
