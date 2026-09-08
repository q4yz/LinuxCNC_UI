// Facade for the Visual HAL editor's backend surface.
//
// Wraps the generated `HalService` client so the view never imports
// generated code directly and never throws raw transport errors into
// the UI: a failed call resolves to `null` and the caller renders an
// error state instead.

import { HalService } from "../../generated/api/services/HalService";
import type { HalFileSaveRequest } from "../../generated/api/models/HalFileSaveRequest";
import type { HalLayoutResponse } from "../../generated/api/models/HalLayoutResponse";

export class HalVisualService {
    /**
     * Fetch the editor layout (IN pins, OUT pins, and — when `file` is
     * given — that file's parsed `net` signals) from
     * `GET /api/v1/hal/layout`.
     *
     * Returns `null` on any HTTP / network failure so callers can
     * render an error state rather than crashing the editor.
     */
    static async fetchLayout(file?: string): Promise<HalLayoutResponse | null> {
        try {
            return await HalService.getLayoutApiV1HalLayoutGet(file);
        } catch (err: unknown) {
            console.error("[HalVisualService] Failed to fetch HAL layout", err);
            return null;
        }
    }

    /**
     * Save the editor's current signal set into `file` via
     * `PUT /api/v1/hal/layout` — rewrites the delimited, warning-
     * commented signals section of that file; everything else in it is
     * left untouched. Returns the freshly re-parsed layout, or `null`
     * on failure.
     */
    static async saveLayout(
        file: string,
        signals: HalFileSaveRequest["signals"],
    ): Promise<HalLayoutResponse | null> {
        try {
            return await HalService.saveLayoutApiV1HalLayoutPut(file, { signals });
        } catch (err: unknown) {
            console.error("[HalVisualService] Failed to save HAL layout", err);
            return null;
        }
    }
}

export default HalVisualService;
