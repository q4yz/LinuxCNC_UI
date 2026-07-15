/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response returned after a successful file upload.
 */
export type UploadFileResponse = {
    /**
     * Outcome summary (e.g., 'ok')
     */
    status: string;
    /**
     * Sanitized filename that was stored on disk
     */
    filename: string;
    /**
     * Human-readable upload confirmation
     */
    message: string;
};

