// Facade for the Visual HAL editor's single backend surface.
//
// Wraps the generated `HalService` client so the Pinia store never
// imports generated code directly and never throws raw transport
// errors into the UI: a failed layout fetch resolves to `null` and
// the store surfaces the described error instead.

import { HalService } from "../../generated/api/services/HalService";
import type { HalLayoutResponse } from "../../generated/api/models/HalLayoutResponse";

export class HalVisualService {
    /**
     * Fetch the full editor layout (IN pins, OUT pins, existing
     * signals) from `GET /api/v1/hal/layout`.
     *
     * Returns `null` on any HTTP / network failure so callers can
     * render an error state rather than crashing the editor.
     */
    static async fetchLayout(): Promise<HalLayoutResponse | null> {
        try {
            return await HalService.getLayoutApiV1HalLayoutGet();
        } catch (err: unknown) {
            console.error("[HalVisualService] Failed to fetch HAL layout", err);
            return null;
        }
    }
}

export default HalVisualService;
