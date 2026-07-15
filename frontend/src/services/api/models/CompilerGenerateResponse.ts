/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CompilerGeneratePreview } from './CompilerGeneratePreview';
/**
 * Response model for POST /compiler/generate/{profile_name}.
 */
export type CompilerGenerateResponse = {
    /**
     * Outcome summary (e.g., 'ok')
     */
    status: string;
    /**
     * Human-readable generation summary
     */
    message: string;
    /**
     * Resolved profile filename that was generated
     */
    profile: string;
    /**
     * Preview text of each generated artifact
     */
    generated_files: CompilerGeneratePreview;
    /**
     * Detailed compiler staging result
     */
    staged?: Record<string, any>;
};

