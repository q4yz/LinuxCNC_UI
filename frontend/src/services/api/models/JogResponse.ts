/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response model for a jog command.
 */
export type JogResponse = {
    /**
     * Outcome summary (e.g., 'ok')
     */
    status: string;
    /**
     * Per-axis hardware layer results keyed by axis index (as string for JSON friendliness)
     */
    results?: Record<string, string>;
};

