/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response model for POST /compiler/deploy.
 */
export type CompilerDeployResponse = {
    /**
     * Outcome summary (e.g., 'ok')
     */
    status: string;
    /**
     * Human-readable deployment summary
     */
    message: string;
    /**
     * Whether the LinuxCNC backend must be restarted for the new configuration to take effect
     */
    restart_required: boolean;
    /**
     * Detailed compiler deployment result
     */
    deployment?: Record<string, any>;
};

