/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response model for GET /system/version.
 */
export type VersionInfoResponse = {
    /**
     * Short git commit hash identifying the running build
     */
    version: string;
    /**
     * Human-readable current release tag
     */
    current_version: string;
    /**
     * Human-readable latest known release tag
     */
    latest_version: string;
    /**
     * Whether a newer release is known to be available
     */
    update_available: boolean;
};

