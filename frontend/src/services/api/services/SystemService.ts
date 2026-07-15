/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SystemUpdateResponse } from '../models/SystemUpdateResponse';
import type { VersionInfoResponse } from '../models/VersionInfoResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SystemService {
    /**
     * Get Version Info
     * Return the current build version, latest known release, and whether an update is available.
     * @returns VersionInfoResponse Successful Response
     * @throws ApiError
     */
    public static getVersionInfo(): CancelablePromise<VersionInfoResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/system/version',
        });
    }
    /**
     * Trigger System Update
     * Schedule scripts/update.sh (git pull + pip install) to run after the response is returned.
     * @returns SystemUpdateResponse Successful Response
     * @throws ApiError
     */
    public static triggerSystemUpdate(): CancelablePromise<SystemUpdateResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/system/update',
        });
    }
}
