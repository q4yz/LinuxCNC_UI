/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response model for GET /compiler/profiles.
 */
export type CompilerProfilesResponse = {
    /**
     * Outcome summary (e.g., 'ok')
     */
    status: string;
    /**
     * List of available profile filenames
     */
    profiles?: Array<string>;
};

