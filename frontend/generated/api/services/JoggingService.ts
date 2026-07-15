/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { JogCommand } from '../models/JogCommand';
import type { JogResponse } from '../models/JogResponse';
import type { JogStatusResponse } from '../models/JogStatusResponse';
import type { JogStopCommand } from '../models/JogStopCommand';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class JoggingService {
    /**
     * Jog Axis
     * Initiates a jog. Supports step, continuous, or stop commands depending on parameters.
     * @param requestBody
     * @returns JogResponse Successful Response
     * @throws ApiError
     */
    public static jogAxis(
        requestBody: JogCommand,
    ): CancelablePromise<JogResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/machine/jog',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Jog Keep-Alive
     * Refreshes the watchdog timer for an actively jogging axis. Must be called frequently.
     * @param requestBody
     * @returns JogStatusResponse Successful Response
     * @throws ApiError
     */
    public static jogKeepalive(
        requestBody: JogStopCommand,
    ): CancelablePromise<JogStatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/machine/jog/keepalive',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Stop Jogging
     * Explicitly stops a continuous jog and removes it from the watchdog.
     * @param requestBody
     * @returns JogStatusResponse Successful Response
     * @throws ApiError
     */
    public static jogStop(
        requestBody: JogStopCommand,
    ): CancelablePromise<JogStatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/machine/jog/stop',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
