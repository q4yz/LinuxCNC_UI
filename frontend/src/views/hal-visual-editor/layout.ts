// Pure geometry helpers for the node canvas. Port anchor points are
// derived purely from `node.x` / `node.y` + port index rather than
// measured from the DOM, so connection lines stay reactive for free
// whenever a node moves or gains/loses a port.

import type { HalNode, Port } from "./types";

export const NODE_WIDTH = 220;
export const HEADER_HEIGHT = 44;
export const PORT_TOP_PADDING = 8;
export const PORT_ROW_HEIGHT = 30;
export const FOOTER_PADDING = 8;
// Horizontal distance from the card's edge to a port dot's center —
// approximates the card/row padding + half the dot's own width so
// wire endpoints line up with the rendered dot rather than the bare
// card border.
export const EDGE_INSET = 18;

export function portOffsetY(index: number): number {
  return HEADER_HEIGHT + PORT_TOP_PADDING + index * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT / 2;
}

function bodyRowCount(node: HalNode, hasAddButton: boolean): number {
  return Math.max(node.inputs.length, node.outputs.length, 1) + (hasAddButton ? 1 : 0);
}

export function nodeHeight(node: HalNode, hasAddButton: boolean): number {
  return HEADER_HEIGHT + PORT_TOP_PADDING + bodyRowCount(node, hasAddButton) * PORT_ROW_HEIGHT + FOOTER_PADDING;
}

export function portAnchor(node: HalNode, port: Port): { x: number; y: number } {
  const list = port.direction === "in" ? node.inputs : node.outputs;
  const index = list.findIndex((p) => p.id === port.id);
  const y = node.y + portOffsetY(index < 0 ? 0 : index);
  const x = port.direction === "in" ? node.x + EDGE_INSET : node.x + NODE_WIDTH - EDGE_INSET;
  return { x, y };
}
