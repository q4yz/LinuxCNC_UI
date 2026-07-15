/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pydantic model for setting machine power state.
 */
export type StateCommand = {
    /**
     * Target machine state: 'on', 'off', 'estop', or 'estop_reset'
     */
    state: string;
};

