/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CompilerDeployResponse } from '../models/CompilerDeployResponse';
import type { CompilerGenerateResponse } from '../models/CompilerGenerateResponse';
import type { CompilerProfilesResponse } from '../models/CompilerProfilesResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CompilerService {
    /**
     * List compiler profiles
     * List all available configuration profiles that can be compiled into LinuxCNC artifacts.
     * @returns CompilerProfilesResponse Successful Response
     * @throws ApiError
     */
    public static listCompilerProfiles(): CancelablePromise<CompilerProfilesResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/compiler/profiles',
        });
    }
    /**
     * Generate staged compiler files
     * Compile the named profile into LinuxCNC artifacts staged under machine_config/ready_for_deploy.
     * @param profileName
     * @returns CompilerGenerateResponse Successful Response
     * @throws ApiError
     */
    public static generateCompilerArtifacts(
        profileName: string,
    ): CancelablePromise<CompilerGenerateResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/compiler/generate/{profile_name}',
            path: {
                'profile_name': profileName,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deploy staged compiler files
     * Promote the staged artifacts in machine_config/ready_for_deploy into machine_config/active and mark the system restart-required.
     * @returns CompilerDeployResponse Successful Response
     * @throws ApiError
     */
    public static deployCompilerArtifacts(): CancelablePromise<CompilerDeployResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/compiler/deploy',
        });
    }
}
