/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ParseResponse } from '../models/ParseResponse';
import type { StatusResponse } from '../models/StatusResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class ProgramExecutionService {
    /**
     * Run Program
     * Start or resume the loaded G-code program from a specific line.
     * @param lineNumber
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static runProgram(
        lineNumber?: number,
    ): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/program/run',
            query: {
                'line_number': lineNumber,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Stop Program
     * Stop/abort the currently running program.
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static stopProgram(): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/program/stop',
        });
    }
    /**
     * Pause Program
     * Pause the currently running program.
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static pauseProgram(): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/program/pause',
        });
    }
    /**
     * Resume Program
     * Resume a paused program.
     * @returns StatusResponse Successful Response
     * @throws ApiError
     */
    public static resumeProgram(): CancelablePromise<StatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/program/resume',
        });
    }
    /**
     * Trigger Parser
     * Manually trigger the Klipper-to-LinuxCNC configuration parser.
     * @returns ParseResponse Successful Response
     * @throws ApiError
     */
    public static triggerParser(): CancelablePromise<ParseResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/modules/program/parse',
        });
    }
}
