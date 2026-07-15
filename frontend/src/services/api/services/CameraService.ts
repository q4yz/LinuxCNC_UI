/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CameraService {
    /**
     * Get Live Camera Stream
     * Streams live video from the primary USB webcam using MJPEG.
     * @returns any Successful Response
     * @throws ApiError
     */
    public static cameraStreamApiV1CameraStreamGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/camera/stream',
        });
    }
}
