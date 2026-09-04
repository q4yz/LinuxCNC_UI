// Mock external HAL pin palette for the Visual HAL Editor concept.
//
// Standing in for a real `GET /hal/pins` response so the canvas UI
// can be designed and tested without any backend. Shapes mirror
// `HalPinResource` loosely (full_name / type / direction) but this
// file is the only place that knows about it — the rest of the
// editor talks to `MockPin` from ./types.

import type { MockPin } from "./types";

export const MOCK_PINS: MockPin[] = [
  // --- bit, writers (things that drive a signal) ---
  { id: "p1", fullName: "parport.0.pin-10-in", type: "bit", direction: "out", description: "E-stop button (physical input)" },
  { id: "p2", fullName: "parport.0.pin-11-in", type: "bit", direction: "out", description: "X limit switch" },
  { id: "p3", fullName: "parport.0.pin-12-in", type: "bit", direction: "out", description: "Y limit switch" },
  { id: "p4", fullName: "parport.0.pin-13-in", type: "bit", direction: "out", description: "Z limit switch" },
  { id: "p5", fullName: "probe.din", type: "bit", direction: "out", description: "Touch probe contact" },
  { id: "p6", fullName: "spindle.0.at-speed", type: "bit", direction: "out", description: "Spindle reached commanded speed" },
  { id: "p7", fullName: "motion.in-position", type: "bit", direction: "out", description: "Motion controller settled" },
  { id: "p8", fullName: "halui.machine.is-on", type: "bit", direction: "out", description: "Machine power state" },

  // --- bit, readers (things that consume a signal) ---
  { id: "p9", fullName: "parport.0.pin-01-out", type: "bit", direction: "in", description: "Physical output pin" },
  { id: "p10", fullName: "spindle.0.on", type: "bit", direction: "in", description: "Spindle enable command" },
  { id: "p11", fullName: "coolant.mist", type: "bit", direction: "in", description: "Mist coolant relay" },
  { id: "p12", fullName: "coolant.flood", type: "bit", direction: "in", description: "Flood coolant relay" },
  { id: "p13", fullName: "axis.0.amp-enable-out", type: "bit", direction: "in", description: "X axis drive enable" },
  { id: "p14", fullName: "iocontrol.0.emc-enable-in", type: "bit", direction: "in", description: "E-stop chain feedback" },
  { id: "p15", fullName: "halui.program.is-paused", type: "bit", direction: "in", description: "Program pause indicator lamp" },

  // --- float, writers ---
  { id: "p16", fullName: "encoder.0.position", type: "float", direction: "out", description: "Spindle encoder position" },
  { id: "p17", fullName: "pid.0.output", type: "float", direction: "out", description: "Axis PID loop output" },
  { id: "p18", fullName: "motion.spindle-speed-out", type: "float", direction: "out", description: "Commanded spindle speed" },

  // --- float, readers ---
  { id: "p19", fullName: "pid.0.command", type: "float", direction: "in", description: "Axis PID setpoint" },
  { id: "p20", fullName: "pwmgen.0.value", type: "float", direction: "in", description: "PWM duty cycle input" },
  { id: "p21", fullName: "spindle.0.speed-cmd", type: "float", direction: "in", description: "Spindle VFD speed command" },

  // --- s32, writers ---
  { id: "p22", fullName: "encoder.0.count", type: "s32", direction: "out", description: "Raw encoder tick count" },
  { id: "p23", fullName: "stepgen.0.count", type: "s32", direction: "out", description: "Step generator feedback count" },

  // --- s32, readers ---
  { id: "p24", fullName: "gpio.0.step-count-target", type: "s32", direction: "in", description: "Step target counter" },

  // --- u32, writers ---
  { id: "p25", fullName: "encoder.0.raw-counts", type: "u32", direction: "out", description: "Unsigned raw count register" },

  // --- u32, readers ---
  { id: "p26", fullName: "watchdog.0.timeout-count", type: "u32", direction: "in", description: "Watchdog trip counter" },
];

export function findMockPin(id: string): MockPin | undefined {
  return MOCK_PINS.find((pin) => pin.id === id);
}
