/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pydantic model for stopping a jog or sending a keep-alive ping.
 */
export type JogStopCommand = {
    /**
     * Axis indices affected by this stop / keepalive call
     */
    axes: Array<number>;
};

