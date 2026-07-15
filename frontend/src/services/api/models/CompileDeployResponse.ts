/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response model for the legacy /config/compile/deploy endpoint.
 */
export type CompileDeployResponse = {
    /**
     * Outcome summary (e.g., 'ok')
     */
    status: string;
    /**
     * Compiler-reported deployment result details
     */
    result: Record<string, any>;
};

