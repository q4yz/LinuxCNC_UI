/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pydantic model for homing an axis.
 */
export type HomeCommand = {
    /**
     * Axis index to home (0=X, 1=Y, 2=Z). Use -1 to home all axes.
     */
    axis: number;
};

