export const WORK_COORDINATE_SYSTEMS = [
  { index: 1, name: 'G54' },
  { index: 2, name: 'G55' },
  { index: 3, name: 'G56' },
  { index: 4, name: 'G57' },
  { index: 5, name: 'G58' },
  { index: 6, name: 'G59' },
  { index: 7, name: 'G59.1' },
  { index: 8, name: 'G59.2' },
  { index: 9, name: 'G59.3' },
];

export const generateCoordinateSystemCommand = (index) => {
  const system = WORK_COORDINATE_SYSTEMS.find(sys => sys.index === index);
  return system ? system.name : 'G54';
};

/**
 * Generates the MDI command to set the current position of a specific axis.
 * Uses G10 L20 P0, which sets the active coordinate system offset.
 */
export const generateSetOffset = (axisName, value) => {
  // E.g., if axisName='X' and value=0, returns "G10 L20 P0 X0"
  return `G10 L20 P0 ${axisName}${value}`;
};

// ---------------------------------------------------------------------- //
// Default macro templates                                                 //
// ---------------------------------------------------------------------- //
//
// The macro subsystem (issue #7) seeds the macros directory on first
// boot with a single example that demonstrates the hybrid G-code +
// Python feature. Keeping the content here means the backend seeder
// and a future "New macro from template" UI can share the same
// source of truth without duplicating the body.

export const DEFAULT_MACROS = {
  probe_grid: {
    name: 'probe_grid.macro',
    description: 'Probe a 3x3 grid using a Python loop',
    content: `; probe_grid.macro
;
; Demonstrates the hybrid G-code + Python language. Everything
; outside of { ... } is G-code sent to LinuxCNC; everything
; inside the braces is executed as Python with a 'cnc' object
; that mirrors the LinuxCNC command interface.

G21 ; Set units to mm
G90 ; Absolute positioning
G0 Z10 ; Move safely above workpiece

{
    # 'cnc' is injected by the backend. It exposes:
    #   cnc.emit("G0 X0 Y0")      -> send G-code to the controller
    #   cnc.log("...")            -> log to the editor console
    #   cnc.warn("...")           -> log as a warning
    #   cnc.get_pos()             -> read current head position
    grid_size = 3
    spacing = 15.0
    for x in range(grid_size):
        for y in range(grid_size):
            x_pos = x * spacing
            y_pos = y * spacing
            cnc.emit(f"G0 X{x_pos} Y{y_pos}")
            cnc.emit("G38.2 Z-5 F100 ; Probe down")
            cnc.emit("G0 Z10 ; Retract")
            cnc.log(f"Probed point {x}, {y}")
}

G0 X0 Y0
M2 ; End program
`,
  },
  homing: {
    name: 'homing.macro',
    description: 'Home all axes and move to a safe idle position',
    content: `; homing.macro
; Quick homing routine.

G21 ; mm
G91 ; relative mode for the homing move
{
    cnc.emit("G28 Z")
    cnc.emit("G28 X")
    cnc.emit("G28 Y")
    cnc.log("Homing complete")
}
G90 ; back to absolute
G0 X0 Y0 Z10
`,
  },
};
