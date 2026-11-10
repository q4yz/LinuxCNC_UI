export const WORK_COORDINATE_SYSTEMS: ReadonlyArray<{ index: number; name: string }> = [
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

export const generateCoordinateSystemCommand = (index: number): string => {
  const system = WORK_COORDINATE_SYSTEMS.find(sys => sys.index === index);
  return system ? system.name : 'G54';
};

/**
 * Generates the MDI command to set the current position of a specific axis.
 * Uses G10 L20 P0, which sets the active coordinate system offset.
 */
export const generateSetOffset = (axisName: string, value: number | string): string => {
  // E.g., if axisName='X' and value=0, returns "G10 L20 P0 X0"
  return `G10 L20 P0 ${axisName}${value}`;
};

// ---------------------------------------------------------------------- //
// Autocomplete command dictionary                                        //
// ---------------------------------------------------------------------- //
//
// Each entry is a short label plus its full command string. The
// console autocomplete suggests these as the user types. The format
// closely mirrors the existing ``WORK_COORDINATE_SYSTEMS`` shape so
// callers can iterate it with the same code path.
//
// Categories:
//   * ``gcode``  — modal G-codes (motion, units, coords, cutter comp).
//   * ``mcode``  — M-codes (spindle, coolant, tool change, program end).
//   * ``macro``  — the UI's own commands (Z_TILT_ADJUST, BED_MESH_CALIBRATE,
//                  PROBE_ACCURACY, SET_LED, G29): named like Klipper's.
//
// All commands are upper-cased so the autocompletion is case
// insensitive against the user's input. ``LINUXCNC`` literals are
// also valid in lower case per the interpreter, but the canonical
// form is upper case and that is what we surface in the menu.

export const AUTOCOMPLETE_COMMANDS: ReadonlyArray<{ label: string; command: string; category: string; description: string }> = [
  // Motion / interpolation G-codes.
  { label: 'G0',  command: 'G0',   category: 'gcode',  description: 'Rapid move' },
  { label: 'G1',  command: 'G1',   category: 'gcode',  description: 'Linear move' },
  { label: 'G2',  command: 'G2',   category: 'gcode',  description: 'Clockwise arc' },
  { label: 'G3',  command: 'G3',   category: 'gcode',  description: 'Counter-clockwise arc' },
  { label: 'G4',  command: 'G4',   category: 'gcode',  description: 'Dwell (P<seconds>)' },
  { label: 'G10', command: 'G10',  category: 'gcode',  description: 'Set coordinate system offset' },
  { label: 'G17', command: 'G17',  category: 'gcode',  description: 'XY plane select' },
  { label: 'G18', command: 'G18',  category: 'gcode',  description: 'XZ plane select' },
  { label: 'G19', command: 'G19',  category: 'gcode',  description: 'YZ plane select' },
  { label: 'G20', command: 'G20',  category: 'gcode',  description: 'Inch units' },
  { label: 'G21', command: 'G21',  category: 'gcode',  description: 'Millimetre units' },
  { label: 'G28', command: 'G28',  category: 'gcode',  description: '# home: the [homing_override] routine, or every axis (Z on the probe last)' },
  { label: 'G30', command: 'G30',  category: 'gcode',  description: 'Return to predefined home' },
  { label: 'G40', command: 'G40',  category: 'gcode',  description: 'Cutter compensation off' },
  { label: 'G41', command: 'G41',  category: 'gcode',  description: 'Cutter compensation left' },
  { label: 'G42', command: 'G42',  category: 'gcode',  description: 'Cutter compensation right' },
  { label: 'G43', command: 'G43',  category: 'gcode',  description: 'Tool length offset' },
  { label: 'G49', command: 'G49',  category: 'gcode',  description: 'Cancel tool length offset' },
  { label: 'G53', command: 'G53',  category: 'gcode',  description: 'Move in machine coordinates' },
  { label: 'G54', command: 'G54',  category: 'gcode',  description: 'Work coordinate system 1' },
  { label: 'G55', command: 'G55',  category: 'gcode',  description: 'Work coordinate system 2' },
  { label: 'G56', command: 'G56',  category: 'gcode',  description: 'Work coordinate system 3' },
  { label: 'G57', command: 'G57',  category: 'gcode',  description: 'Work coordinate system 4' },
  { label: 'G58', command: 'G58',  category: 'gcode',  description: 'Work coordinate system 5' },
  { label: 'G59', command: 'G59',  category: 'gcode',  description: 'Work coordinate system 6' },
  { label: 'G80', command: 'G80',  category: 'gcode',  description: 'Cancel motion mode' },
  { label: 'G90', command: 'G90',  category: 'gcode',  description: 'Absolute distance mode' },
  { label: 'G91', command: 'G91',  category: 'gcode',  description: 'Incremental distance mode' },
  { label: 'G92', command: 'G92',  category: 'gcode',  description: 'Coordinate system offset' },
  { label: 'G94', command: 'G94',  category: 'gcode',  description: 'Feed per minute mode' },
  { label: 'G95', command: 'G95',  category: 'gcode',  description: 'Feed per revolution mode' },
  { label: 'G96', command: 'G96',  category: 'gcode',  description: 'Constant surface speed' },
  { label: 'G97', command: 'G97',  category: 'gcode',  description: 'Constant RPM' },
  { label: 'G98', command: 'G98',  category: 'gcode',  description: 'Retract to initial plane' },
  { label: 'G99', command: 'G99',  category: 'gcode',  description: 'Retract to R plane' },

  // M-codes.
  { label: 'M0',  command: 'M0',   category: 'mcode',  description: 'Program stop' },
  { label: 'M1',  command: 'M1',   category: 'mcode',  description: 'Optional stop' },
  { label: 'M2',  command: 'M2',   category: 'mcode',  description: 'Program end' },
  { label: 'M3',  command: 'M3',   category: 'mcode',  description: 'SpindleDigital on (CW)' },
  { label: 'M4',  command: 'M4',   category: 'mcode',  description: 'SpindleDigital on (CCW)' },
  { label: 'M5',  command: 'M5',   category: 'mcode',  description: 'SpindleDigital off' },
  { label: 'M6',  command: 'M6',   category: 'mcode',  description: 'Tool change' },
  { label: 'M7',  command: 'M7',   category: 'mcode',  description: 'Mist coolant on' },
  { label: 'M8',  command: 'M8',   category: 'mcode',  description: 'Flood coolant on' },
  { label: 'M9',  command: 'M9',   category: 'mcode',  description: 'Coolant off' },
  { label: 'M30', command: 'M30',  category: 'mcode',  description: 'Program end and rewind' },
  { label: 'M48', command: 'M48',  category: 'mcode',  description: 'Enable speed/feed override' },
  { label: 'M49', command: 'M49',  category: 'mcode',  description: 'Disable speed/feed override' },
  { label: 'M50', command: 'M50',  category: 'mcode',  description: 'Feed override enable' },
  { label: 'M51', command: 'M51',  category: 'mcode',  description: 'SpindleDigital override enable' },
  { label: 'M61', command: 'M61',  category: 'mcode',  description: 'Set current tool' },
  { label: 'M62', command: 'M62',  category: 'mcode',  description: 'Digital output on' },
  { label: 'M63', command: 'M63',  category: 'mcode',  description: 'Digital output off' },
  { label: 'M64', command: 'M64',  category: 'mcode',  description: 'Digital output on (wait)' },
  { label: 'M65', command: 'M65',  category: 'mcode',  description: 'Digital output off (wait)' },
  { label: 'M66', command: 'M66',  category: 'mcode',  description: 'Wait on input' },
  { label: 'M70', command: 'M70',  category: 'mcode',  description: 'Save state' },
  { label: 'M71', command: 'M71',  category: 'mcode',  description: 'Restore state' },
  { label: 'M72', command: 'M72',  category: 'mcode',  description: 'Restore state (alternate)' },

  // The UI's own commands (machine backend, sent like MDI): Klipper names
  // where Klipper has one. The old "HOME" / "POWER ON" / "ESTOP" entries
  // were never translated and went to LinuxCNC as (invalid) MDI.
  { label: 'Z_TILT_ADJUST', command: 'Z_TILT_ADJUST', category: 'macro', description: '# z tilt: probe the points, level the Z motors ([z_tilt])' },
  { label: 'BED_MESH_CALIBRATE', command: 'BED_MESH_CALIBRATE', category: 'macro', description: '# bed mesh: probe the grid, save and activate it (PROFILE=<name>)' },
  { label: 'PROBE_ACCURACY', command: 'PROBE_ACCURACY SAMPLES=10', category: 'macro', description: '# probe repeatability: min, max, range, mean, median, std dev' },
  { label: 'SET_LED', command: 'SET_LED LED= RED=1 GREEN=1 BLUE=1', category: 'macro', description: '# set a [neopixel] colour (0 ... 1, INDEX=<n> for one segment)' },
  { label: 'G29', command: 'G29', category: 'macro', description: '# level: Z_TILT_ADJUST, then BED_MESH_CALIBRATE' },
  { label: 'G28 X Y', command: 'G28 X Y', category: 'macro', description: '# home the axes named (Z on the probe last)' },
  // Printer M-codes (REMAPs in the machine's m_codes folder).
  { label: 'M104', command: 'M104 S200', category: 'mcode', description: '# set extruder temperature (no wait)' },
  { label: 'M109', command: 'M109 S200', category: 'mcode', description: '# set extruder temperature and wait' },
  { label: 'M140', command: 'M140 S60',  category: 'mcode', description: '# set bed temperature (no wait)' },
  { label: 'M190', command: 'M190 S60',  category: 'mcode', description: '# set bed temperature and wait' },
  { label: 'M106', command: 'M106 S255', category: 'mcode', description: '# part fan on (S0 ... 255)' },
  { label: 'M107', command: 'M107',      category: 'mcode', description: '# part fan off' },
  { label: 'M150', command: 'M150 R255 U255 B255', category: 'mcode', description: '# LED colour (Marlin)' },
];

/**
 * Filter the autocomplete dictionary against a free-form input.
 * The match is case-insensitive and applied to either the command
 * label or its description. An empty / whitespace-only input
 * returns ``[]`` so the caller can hide the suggestion box.
 *
 * @param {string} query - The current contents of the input field.
 * @param {number} limit - Maximum number of suggestions to return.
 * @returns {Array<{label: string, command: string, category: string, description: string}>}
 */
export const filterAutocompleteCommands = (query: string, limit = 8) => {
  if (typeof query !== 'string') return [];
  const trimmed = query.trim().toUpperCase();
  if (!trimmed) return [];
  const matches = AUTOCOMPLETE_COMMANDS.filter((entry) => {
    return (
      entry.label.toUpperCase().startsWith(trimmed) ||
      entry.description.toUpperCase().includes(trimmed)
    );
  });
  return matches.slice(0, limit);
};
