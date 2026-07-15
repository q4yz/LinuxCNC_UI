/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GeneratedFiles } from './GeneratedFiles';
/**
 * Response model for the legacy /config/compile/generate endpoint.
 */
export type CompileGenerateResponse = {
    /**
     * Outcome summary (e.g., 'ok')
     */
    status: string;
    /**
     * Preview text of each generated artifact
     */
    files: GeneratedFiles;
};

