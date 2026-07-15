/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { HomeCommand } from '../models/HomeCommand';
import type { MdiCommand } from '../models/MdiCommand';
import type { ModeCommand } from '../models/ModeCommand';
import type { StateCommand } from '../models/StateCommand';
import type { StatusResponse } from '../models/StatusResponse';
import type { TemperatureRequest } from '../models/TemperatureRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class MachineStateService {
    /**
     * Set Machine State
     * Toggle machine E-Stop or Power state.
     * @param requestBody
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static setMachineState(
        requestBody: StateCommand,
    ): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/machine/state',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Set Machine Mode
     * Change the machine task mode (manual, auto, mdi).
     * @param requestBody
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static setMachineMode(
        requestBody: ModeCommand,
    ): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/machine/mode',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Home Axis
     * Home a specific axis, or all axes if axis=-1.
     * @param requestBody
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static homeAxis(
        requestBody: HomeCommand,
    ): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/machine/home',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Run MDI Command
     * Execute a single MDI (G-Code) command. Automatically switches the machine to MDI mode.
     * @param requestBody
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static runMdiCommand(
        requestBody: MdiCommand,
    ): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/machine/mdi',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Set Target Temperature
     * Set the target temperature for the spindle/extruder heater.
     * @param requestBody
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static setTargetTemperature(
        requestBody: TemperatureRequest,
    ): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/machine/temperature',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
