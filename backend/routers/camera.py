import cv2
import time
import threading
import asyncio
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger("backend.routers.camera")

router = APIRouter(prefix="/api/v1/camera", tags=["Camera"])


# Global variables for the frame buffer thread
_latest_frame = None
_camera_thread = None
_camera_lock = threading.Lock()


def _camera_worker():
    """
    Background thread that connects to the USB webcam and
    maintains a single global frame buffer at a restricted framerate.
    """
    global _latest_frame
    logger.info("Starting background camera thread...")
    cap = cv2.VideoCapture(0)
    
    # 1. Reduce Resolution for lower latency
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    try:
        while True:
            success, frame = cap.read()
            if not success:
                logger.error("Failed to read frame from camera.")
                time.sleep(1) # Wait before retrying
                continue
            
            # 2. Reduce Quality (70%) for smaller payload size
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
            ret, buffer = cv2.imencode('.jpg', frame, encode_param)
            if ret:
                with _camera_lock:
                    _latest_frame = buffer.tobytes()
            
            # 3. Cap at ~15 FPS and yield the thread so the OS isn't starved
            time.sleep(0.06)
    finally:
        # CRITICAL: Always cleanly release the webcam resources
        cap.release()
        logger.info("Camera resources released.")


async def generate_frames():
    """
    Async generator yielding the latest frame from the global buffer.
    Because it yields the async event loop, it will not block WebSocket telemetry/jogging.
    """
    global _camera_thread
    
    # Lazily start the background hardware thread if it isn't running
    if _camera_thread is None or not _camera_thread.is_alive():
        _camera_thread = threading.Thread(target=_camera_worker, daemon=True)
        _camera_thread.start()

    while True:
        with _camera_lock:
            frame_bytes = _latest_frame
            
        if frame_bytes is not None:
            # Yield the MJPEG byte payload
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        # CRITICAL: Cap client stream framerate to ~15 FPS and explicitly yield the asyncio event loop!
        # This ensures WebSocket jog Keep-Alives are processed immediately by FastAPI.
        await asyncio.sleep(0.06)

@router.get("/stream", summary="Get Live Camera Stream", description="Streams live video from the primary USB webcam using MJPEG.")
def camera_stream():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")