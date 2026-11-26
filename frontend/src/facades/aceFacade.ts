// The ACE Pro filament unit (machine backend, ``/api/v1/ace``): state,
// tool change (runs M640 through MDI), manual feed / unwind, dryer, and
// correcting the loaded slot. Thin pass-through: callers report errors.

import { AceService } from "../../generated/api/index";
import type { AceStateResponse } from "../../generated/api/index";

export type AceState = AceStateResponse;

export const aceFacade = {
  get: (): Promise<AceState> => AceService.getAceState(),
  /** Load ``slot`` (0-3), or -1 to unload: park, cut, change, purge. */
  change: (slot: number): Promise<AceState> => AceService.aceChangeTool({ slot }),
  feed: (index: number, length: number, speed: number): Promise<AceState> =>
    AceService.aceFeed(index, { length, speed }),
  unwind: (index: number, length: number, speed: number): Promise<AceState> =>
    AceService.aceUnwind(index, { length, speed }),
  startDrying: (temp: number, minutes: number): Promise<AceState> => AceService.aceStartDrying({ temp, minutes }),
  stopDrying: (): Promise<AceState> => AceService.aceStopDrying(),
  /** The slot that is really loaded after handling filament by hand (-1: none). */
  setCurrent: (slot: number): Promise<AceState> => AceService.aceSetCurrentSlot({ slot }),
};

export default aceFacade;
