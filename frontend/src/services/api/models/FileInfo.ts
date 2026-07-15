/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Metadata describing a single G-code file on disk.
 */
export type FileInfo = {
    /**
     * Filename (basename, no path)
     */
    filename: string;
    /**
     * File size in bytes
     */
    size_bytes: number;
    /**
     * ISO-8601 timestamp of the last modification
     */
    modified: string;
};

