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