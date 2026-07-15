/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pydantic model for setting a sensor target temperature.
 */
export type TemperatureRequest = {
    /**
     * Logical sensor identifier (e.g., 'extruder', 'bed')
     */
    sensor_name: string;
    /**
     * Target temperature in Celsius
     */
    target: number;
};

