// LED facade — WS2812 / SK6812 chains from [neopixel] sections
// (machine backend ``/api/v1/leds``, `.agent/component/neopixel.md`).
// Colours are Klipper's SET_LED channels, 0 ... 1.

import { LedsService } from "../../generated/api/index";
import type { Led } from "../../generated/api/index";
import { colorToHex, hexToColor, type LedColor } from "../components/io/ledColor";

export type { Led, LedColor };
export { colorToHex, hexToColor };

export const ledsFacade = {
  list: (): Promise<Led[]> => LedsService.getLeds(),
  /** ``index``: an LED number (from 1) — sets the segment it is in; none: the whole chain. */
  set: (id: string, color: LedColor, index?: number): Promise<Led[]> =>
    LedsService.setLed(id, { ...color, white: 0, index: index ?? null }),
};

export default ledsFacade;
