/**
 * Configuration and helpers for generating standard G-code strings.
 * Centralizing these allows for easy modification if the machine 
 * requires a different dialect or specific syntax.
 */

// Available Work Coordinate Systems (WCS)
// Maps the backend integer index (1-9) to the standard G-code name.
export const WORK_COORDINATE_SYSTEMS = [
  { index: 1, name: 'G54' },
  { index: 2, name: 'G55' },
  { index: 3, name: 'G56' },
  { index: 4, name: 'G57' },
  { index: 5, name: 'G58' },
  { index: 6, name: 'G59' },
  { index: 7, name: 'G59.1' },
  { index: 8, name: 'G59.2' },
  { index: 9, name: 'G59.3' }
];

/**
 * Generates the MDI command to set the current position of an axis 
 * to a specific value in the active coordinate system.
 * Uses G10 L20 P0 (P0 means active coordinate system).
 * 
 * @param {string} axis - The axis character (e.g., 'X', 'Y', 'Z')
 * @param {number|string} value - The numerical coordinate value
 * @returns {string} The raw G-code string
 */
export const generateSetOffset = (axis, value) => {
  return `G10 L20 P0 ${axis.toUpperCase()}${value}`;
};
