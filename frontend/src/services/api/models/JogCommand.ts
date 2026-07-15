/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pydantic model for executing a jog.
 */
export type JogCommand = {
    /**
     * Mapping of axis index (0=X, 1=Y, 2=Z) to signed jog velocity in user units per minute
     */
    velocities: Record<string, number>;
    /**
     * Absolute step distance in mm; non-zero enables an incremental jog instead of continuous
     */
    distance?: number;
};

