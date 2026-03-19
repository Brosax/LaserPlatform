"""
Allied Vision camera adapter.

Provides a simplified interface for single-frame capture from Allied Vision
cameras via the VmbPy (Vimba X) SDK. Designed for use in grid scanning
where individual frames are captured at each position.

Also provides a ``LiveFeedWorker`` QThread for continuous streaming,
used by the GUI to display a real-time camera preview.
"""

import logging
from typing import Optional, Tuple

import numpy as np
from PySide6 import QtCore

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Live-feed worker (QThread)
# ------------------------------------------------------------------ #


class LiveFeedWorker(QtCore.QThread):
    """
    QThread that continuously grabs frames from the camera and emits
    them as numpy arrays.

    The worker operates on an *already-open* CameraAdapter — it calls
    ``camera.get_frame()`` in a tight loop and emits ``frame_ready``
    for each successful grab.

    Signals
    -------
    frame_ready(np.ndarray)
        Emitted for each new frame (uint16, Mono14 data).
    error_occurred(str)
        Emitted when a fatal error stops streaming.
    """

    frame_ready = QtCore.Signal(object)  # np.ndarray
    error_occurred = QtCore.Signal(str)

    MAX_CONSECUTIVE_TIMEOUTS = 10

    def __init__(self, camera_adapter: "CameraAdapter", parent=None):
        super().__init__(parent)
        self._camera_adapter = camera_adapter
        self._running = False

    # -- public API --------------------------------------------------

    def stop(self):
        """Request the worker to stop after the current frame grab."""
        self._running = False

    @property
    def is_streaming(self) -> bool:
        return self._running and self.isRunning()

    # -- thread entry ------------------------------------------------

    def run(self):
        """Main loop: grab frames until ``stop()`` is called."""
        import vmbpy

        self._running = True
        consecutive_timeouts = 0
        cam = self._camera_adapter._camera

        if cam is None:
            self.error_occurred.emit("Camera is not open.")
            return

        logger.info("Live feed streaming started.")
        while self._running:
            try:
                frame = cam.get_frame(timeout_ms=500)
                image = np.squeeze(frame.as_numpy_ndarray().copy())
                self.frame_ready.emit(image)
                consecutive_timeouts = 0
            except vmbpy.VmbTimeout:
                consecutive_timeouts += 1
                if consecutive_timeouts >= self.MAX_CONSECUTIVE_TIMEOUTS:
                    self.error_occurred.emit(
                        f"Camera timed out {consecutive_timeouts} consecutive times."
                    )
                    break
            except Exception as exc:
                self.error_occurred.emit(str(exc))
                break

        self._running = False
        logger.info("Live feed streaming stopped.")


class CameraAdapter:
    """
    Adapter for Allied Vision cameras using the VmbPy SDK.

    Wraps the VmbPy context management to provide a simple
    open/configure/capture/close interface for grid scanning.

    Usage
    -----
    ```python
    adapter = CameraAdapter()
    adapter.open()
    adapter.configure(exposure_us=1000.0)
    image = adapter.capture_single()
    adapter.close()
    ```
    """

    def __init__(self, camera_id: Optional[str] = None):
        """
        Parameters
        ----------
        camera_id : str, optional
            Identifier of the camera to use. If None, the first
            available camera will be selected.
        """
        self._camera_id = camera_id
        self._vmb = None
        self._camera = None
        self._is_open = False

    def open(self):
        """
        Open the Vimba system and the camera.

        Raises
        ------
        RuntimeError
            If no camera is found or the specified camera ID is invalid.
        """
        import vmbpy

        self._vmb = vmbpy.VmbSystem.get_instance()
        self._vmb.__enter__()

        try:
            if self._camera_id:
                self._camera = self._vmb.get_camera_by_id(self._camera_id)
            else:
                cameras = self._vmb.get_all_cameras()
                if not cameras:
                    raise RuntimeError("No Allied Vision cameras detected.")
                self._camera = cameras[0]
                self._camera_id = self._camera.get_id()
                logger.info(
                    f"Auto-selected camera: {self._camera.get_name()} "
                    f"(ID: {self._camera_id})"
                )

            self._camera.__enter__()
            self._is_open = True
            logger.info(f"Camera opened: {self._camera.get_name()}")

        except Exception:
            self._vmb.__exit__(None, None, None)
            self._vmb = None
            raise

    def close(self):
        """Close the camera and Vimba system."""
        if self._camera is not None:
            try:
                self._camera.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing camera: {e}")
            self._camera = None

        if self._vmb is not None:
            try:
                self._vmb.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Vimba system: {e}")
            self._vmb = None

        self._is_open = False
        logger.info("Camera closed.")

    def configure(
        self,
        exposure_us: float,
        auto_exposure: bool = False,
        gain: Optional[float] = None,
        pixel_format: str = "Mono14",
    ):
        """
        Configure the camera for single-frame capture.

        Parameters
        ----------
        exposure_us : float
            Exposure time in microseconds.
        auto_exposure : bool
            Whether to enable automatic exposure control.
        gain : float, optional
            Sensor gain. If None, auto-gain is used or the current value is kept.
        pixel_format : str
            Pixel format string (default "Mono14" for NIR imaging).
        """
        import vmbpy

        if not self._is_open:
            raise RuntimeError("Camera is not open. Call open() first.")

        # Set pixel format
        format_map = {
            "Mono8": vmbpy.PixelFormat.Mono8,
            "Mono10": vmbpy.PixelFormat.Mono10,
            "Mono12": vmbpy.PixelFormat.Mono12,
            "Mono14": vmbpy.PixelFormat.Mono14,
        }
        if pixel_format in format_map:
            self._camera.set_pixel_format(format_map[pixel_format])
            logger.info(f"Pixel format set to: {pixel_format}")
        else:
            logger.warning(
                f"Unknown pixel format '{pixel_format}', using camera default."
            )

        # Set exposure mode/time
        if auto_exposure:
            try:
                self._camera.get_feature_by_name("ExposureAuto").set("Continuous")
                logger.info("Auto exposure enabled (Continuous).")
            except Exception as e:
                logger.warning(f"Could not enable auto exposure: {e}")
        else:
            try:
                self._camera.get_feature_by_name("ExposureAuto").set("Off")
            except Exception as e:
                logger.debug(f"Could not set ExposureAuto to Off: {e}")

            try:
                self._camera.get_feature_by_name("ExposureTime").set(exposure_us)
                logger.info(f"Exposure time set to: {exposure_us} us")
            except Exception as e:
                logger.warning(f"Could not set exposure time: {e}")

        # Set gain if specified
        if gain is not None:
            try:
                self._camera.get_feature_by_name("Gain").set(gain)
                logger.info(f"Gain set to: {gain}")
            except Exception as e:
                logger.warning(f"Could not set gain: {e}")

    def capture_single(self, timeout_ms: int = 5000) -> np.ndarray:
        """
        Capture a single frame from the camera.

        Parameters
        ----------
        timeout_ms : int
            Timeout for frame acquisition in milliseconds.

        Returns
        -------
        np.ndarray
            Image as a 2D numpy array with original bit depth.

        Raises
        ------
        RuntimeError
            If camera is not open or capture fails.
        """
        if not self._is_open:
            raise RuntimeError("Camera is not open. Call open() first.")

        frame = self._camera.get_frame(timeout_ms=timeout_ms)
        image = np.squeeze(frame.as_numpy_ndarray().copy())

        logger.debug(f"Captured frame: {image.shape}, dtype={image.dtype}")
        return image

    def get_image_shape(self) -> Tuple[int, int]:
        """
        Get the image dimensions from the camera.

        Returns
        -------
        Tuple[int, int]
            (height, width) of the image.
        """
        if not self._is_open:
            raise RuntimeError("Camera is not open. Call open() first.")

        width = self._camera.get_feature_by_name("Width").get()
        height = self._camera.get_feature_by_name("Height").get()
        return (int(height), int(width))

    @property
    def is_open(self) -> bool:
        """Whether the camera is currently open."""
        return self._is_open

    @property
    def camera_name(self) -> str:
        """Name of the connected camera."""
        if self._camera is not None:
            return self._camera.get_name()
        return "N/A"

    @staticmethod
    def list_cameras() -> list[dict]:
        """
        List all available Allied Vision cameras.

        Returns
        -------
        list[dict]
            List of dicts with 'id' and 'name' for each camera.
        """
        import vmbpy

        cameras = []
        with vmbpy.VmbSystem.get_instance() as vmb:
            for cam in vmb.get_all_cameras():
                cameras.append(
                    {
                        "id": cam.get_id(),
                        "name": cam.get_name(),
                    }
                )
        return cameras
