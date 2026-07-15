/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { Body_uploadFile } from '../models/Body_uploadFile';
import type { FileInfo } from '../models/FileInfo';
import type { LoadProgramRequest } from '../models/LoadProgramRequest';
import type { routers__files__StatusMessageResponse } from '../models/routers__files__StatusMessageResponse';
import type { UploadFileResponse } from '../models/UploadFileResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class NcFilesService {
    /**
     * List Files
     * Returns a list of all G-code files in the nc_files directory.
     * @returns FileInfo Successful Response
     * @throws ApiError
     */
    public static listFiles(): CancelablePromise<Array<FileInfo>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/ncfiles',
        });
    }
    /**
     * Upload File
     * Uploads a G-code file to the nc_files directory.
     * @param formData
     * @returns UploadFileResponse Successful Response
     * @throws ApiError
     */
    public static uploadFile(
        formData: Body_uploadFile,
    ): CancelablePromise<UploadFileResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/ncfiles/upload',
            formData: formData,
            mediaType: 'multipart/form-data',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Delete File
     * Deletes a G-code file from the nc_files directory.
     * @param filename
     * @returns routers__files__StatusMessageResponse Successful Response
     * @throws ApiError
     */
    public static deleteFile(
        filename: string,
    ): CancelablePromise<routers__files__StatusMessageResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/ncfiles/{filename}',
            path: {
                'filename': filename,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Load G-Code Program
     * Loads a previously uploaded G-code file into the LinuxCNC interpreter.
     * @param requestBody
     * @returns routers__files__StatusMessageResponse Successful Response
     * @throws ApiError
     */
    public static loadProgram(
        requestBody: LoadProgramRequest,
    ): CancelablePromise<routers__files__StatusMessageResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/ncfiles/load_program',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
