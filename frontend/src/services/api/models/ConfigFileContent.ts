/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response model for GET /config/{filename}.
 */
export type ConfigFileContent = {
    /**
     * Sanitized filename that was read
     */
    filename: string;
    /**
     * Raw text content of the profile file
     */
    content: string;
};

