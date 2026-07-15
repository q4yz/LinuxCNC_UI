/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CompileDeployResponse } from '../models/CompileDeployResponse';
import type { CompileGenerateResponse } from '../models/CompileGenerateResponse';
import type { ConfigContent } from '../models/ConfigContent';
import type { ConfigFileContent } from '../models/ConfigFileContent';
import type { ConfigProfileInfo } from '../models/ConfigProfileInfo';
import type { routers__config__StatusMessageResponse } from '../models/routers__config__StatusMessageResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class ConfigurationService {
    /**
     * List Config Profiles
     * Returns all profile configuration files from machine_config/profiles.
     * @returns ConfigProfileInfo Successful Response
     * @throws ApiError
     */
    public static listConfigs(): CancelablePromise<Array<ConfigProfileInfo>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/config',
        });
    }
    /**
     * Read Profile File
     * Returns raw text content of a profile file from machine_config/profiles.
     * @param filename
     * @returns ConfigFileContent Successful Response
     * @throws ApiError
     */
    public static readConfig(
        filename: string,
    ): CancelablePromise<ConfigFileContent> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/config/{filename}',
            path: {
                'filename': filename,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Save Profile File
     * Overwrites a profile file in machine_config/profiles.
     * @param filename
     * @param requestBody
     * @returns routers__config__StatusMessageResponse Successful Response
     * @throws ApiError
     */
    public static saveConfig(
        filename: string,
        requestBody: ConfigContent,
    ): CancelablePromise<routers__config__StatusMessageResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/config/{filename}',
            path: {
                'filename': filename,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Generate Staged Configuration
     * Compile a profile into staged LinuxCNC artifacts in ready_for_deploy.
     * @param profileName
     * @returns CompileGenerateResponse Successful Response
     * @throws ApiError
     */
    public static compileGenerateLegacy(
        profileName: string,
    ): CancelablePromise<CompileGenerateResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/config/compile/generate/{profile_name}',
            path: {
                'profile_name': profileName,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deploy Staged Configuration
     * Deploy staged files from ready_for_deploy into active.
     * @returns CompileDeployResponse Successful Response
     * @throws ApiError
     */
    public static compileDeployLegacy(): CancelablePromise<CompileDeployResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/config/compile/deploy',
        });
    }
}
