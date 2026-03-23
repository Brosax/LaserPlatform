"""
Scan coordinator - orchestrates XY movement and user-confirmed image capture.

Runs the grid scan in a QThread, moving to each position in an S-pattern,
then requesting user confirmation before capturing and saving each image.
Supports pause, resume, and abort controls.
"""

import logging
import os
import time
from typing import Optional

import numpy as np
from PySide6 import QtCore

from ..config import ScanConfig
from ..acquisition.camera_adapter import CameraAdapter
from ..acquisition.xy_table import XYTable
from ..utils.image_io import save_both
from .grid_scanner import GridScanner

logger = logging.getLogger(__name__)


class ScanCoordinator(QtCore.QObject):
    """
    Coordinates the S-pattern grid scan with user confirmation.

    Runs in a worker thread and communicates with the GUI via Qt signals.
    Orchestrates: GridScanner (path) -> XY movement -> user confirmation
    -> CameraAdapter (capture) -> save image.

    At each position the coordinator:
    1. Moves the XY table
    2. Waits for settle time
    3. Emits ``confirm_capture_requested`` and waits for user response
    4. On confirmation, captures and saves the image as ``{row}_{col}``
    5. On skip, moves to the next position

    Signals
    -------
    progress_updated(int, int, str)
        (current_tile, total_tiles, status_message)
    confirm_capture_requested(int, int, float, float)
        (row_1indexed, col_1indexed, x_um, y_um) - requests user to confirm image clarity.
    tile_captured(int, int, int)
        (row, col, tile_index) emitted after each tile is captured and saved.
    scan_finished(str)
        Emitted when the scan completes successfully. Carries the output path.
    scan_error(str)
        Emitted when an unrecoverable error occurs.
    scan_aborted()
        Emitted when the scan is aborted by the user.
    position_updated(float, float)
        (x_um, y_um) current platform position.
    eta_updated(float)
        Estimated time remaining in seconds.
    """

    progress_updated = QtCore.Signal(int, int, str)
    confirm_capture_requested = QtCore.Signal(int, int, float, float)
    tile_captured = QtCore.Signal(int, int, int)
    scan_finished = QtCore.Signal(str)
    scan_error = QtCore.Signal(str)
    scan_aborted = QtCore.Signal()
    position_updated = QtCore.Signal(float, float)
    eta_updated = QtCore.Signal(float)

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)

        self._config: Optional[ScanConfig] = None
        self._xy: Optional[XYTable] = None
        self._camera: Optional[CameraAdapter] = None
        self._grid_scanner: Optional[GridScanner] = None

        # State control
        self._is_running = False
        self._is_paused = False
        self._abort_requested = False
        self._mutex = QtCore.QMutex()
        self._pause_condition = QtCore.QWaitCondition()

        # User confirmation state
        self._capture_confirmed = False
        self._capture_skipped = False
        self._confirm_mutex = QtCore.QMutex()
        self._confirm_condition = QtCore.QWaitCondition()

        # Timing
        self._scan_start_time = 0.0
        self._tile_times: list[float] = []

    def configure(self, config: ScanConfig, xy: XYTable, camera: CameraAdapter):
        """
        Set up the coordinator with all required components.

        Parameters
        ----------
        config : ScanConfig
            Scan configuration.
        xy : XYTable
            XY table controller.
        camera : CameraAdapter
            Camera adapter instance (should already be opened and configured).
        """
        self._config = config
        self._xy = xy
        self._camera = camera
        self._grid_scanner = GridScanner(config)

        logger.info(
            f"Coordinator configured: {config.num_rows}x{config.num_cols} grid, "
            f"{self._grid_scanner.total_positions} positions"
        )

    @QtCore.Slot()
    def run_scan(self):
        """
        Execute the full grid scan. Should be called from a worker thread.

        At each position, the coordinator emits ``confirm_capture_requested``
        and blocks until the GUI calls ``confirm_capture()`` or ``skip_capture()``.
        """
        if self._config is None or self._xy is None or self._camera is None:
            self.scan_error.emit("Coordinator not configured. Call configure() first.")
            return

        self._is_running = True
        self._abort_requested = False
        self._is_paused = False
        self._tile_times.clear()
        self._scan_start_time = time.monotonic()

        config = self._config
        grid = self._grid_scanner
        total = grid.total_positions

        # Ensure output directory exists
        output_dir = config.output_directory or os.path.join(os.getcwd(), "scan_output")
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Scan started: {total} positions, output: {output_dir}")
        self.progress_updated.emit(0, total, "Starting scan...")

        try:
            for idx, (row, col, x_um, y_um) in enumerate(grid.positions):
                # --- Check abort ---
                if self._check_abort():
                    return

                # --- Check pause ---
                self._check_pause()

                tile_start = time.monotonic()

                # 1-indexed for display and filenames
                row_1 = row + 1
                col_1 = col + 1

                # --- Move XY ---
                status = f"Moving to position ({row_1},{col_1}) [{idx + 1}/{total}]"
                self.progress_updated.emit(idx, total, status)
                self._xy.move_to(x_um, y_um)
                self.position_updated.emit(x_um, y_um)

                # --- Settle ---
                if config.settle_time_s > 0:
                    time.sleep(config.settle_time_s)

                # --- Check abort after move ---
                if self._check_abort():
                    return

                # --- Request user confirmation ---
                status = f"Position ({row_1},{col_1}) - Waiting for confirmation..."
                self.progress_updated.emit(idx, total, status)

                self._confirm_mutex.lock()
                self._capture_confirmed = False
                self._capture_skipped = False
                self._confirm_mutex.unlock()

                # Emit signal to GUI (will show dialog)
                self.confirm_capture_requested.emit(row_1, col_1, x_um, y_um)

                # Wait for user response
                self._confirm_mutex.lock()
                while (
                    not self._capture_confirmed
                    and not self._capture_skipped
                    and not self._abort_requested
                ):
                    self._confirm_condition.wait(self._confirm_mutex)
                self._confirm_mutex.unlock()

                # Check if aborted during confirmation
                if self._check_abort():
                    return

                # --- Capture and save (or skip) ---
                if self._capture_confirmed:
                    status = f"Capturing ({row_1},{col_1})..."
                    self.progress_updated.emit(idx, total, status)

                    image = self._camera.capture_single()

                    # Save with row_col naming (1-indexed)
                    filename = f"{row_1}_{col_1}"
                    filepath_base = os.path.join(output_dir, filename)
                    save_both(image, filepath_base)

                    self.tile_captured.emit(row, col, idx)
                    logger.info(
                        f"Captured and saved: {filename} at ({x_um:.1f}, {y_um:.1f}) um"
                    )
                else:
                    logger.info(
                        f"Skipped position ({row_1},{col_1}) at ({x_um:.1f}, {y_um:.1f}) um"
                    )

                # --- Update timing ---
                tile_elapsed = time.monotonic() - tile_start
                self._tile_times.append(tile_elapsed)
                self._update_eta(idx + 1, total)

                self.progress_updated.emit(
                    idx + 1, total, f"Position ({row_1},{col_1}) done"
                )

            # --- Finalize ---
            self._is_running = False
            self.scan_finished.emit(output_dir)
            logger.info(f"Scan completed: {output_dir}")

        except Exception as e:
            self._is_running = False
            error_msg = f"Scan failed: {e}"
            logger.exception(error_msg)
            self.scan_error.emit(error_msg)

    # ------------------------------------------------------------------ #
    #  User confirmation slots (called from GUI thread)
    # ------------------------------------------------------------------ #

    def confirm_capture(self):
        """Called by GUI when user confirms the image is clear."""
        self._confirm_mutex.lock()
        self._capture_confirmed = True
        self._confirm_mutex.unlock()
        self._confirm_condition.wakeAll()

    def skip_capture(self):
        """Called by GUI when user wants to skip this position."""
        self._confirm_mutex.lock()
        self._capture_skipped = True
        self._confirm_mutex.unlock()
        self._confirm_condition.wakeAll()

    # ------------------------------------------------------------------ #
    #  Pause / Resume / Abort
    # ------------------------------------------------------------------ #

    def pause(self):
        """Pause the scan after the current tile completes."""
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()
        logger.info("Scan pause requested.")

    def resume(self):
        """Resume a paused scan."""
        self._mutex.lock()
        self._is_paused = False
        self._mutex.unlock()
        self._pause_condition.wakeAll()
        logger.info("Scan resumed.")

    def abort(self):
        """Abort the scan after the current tile completes."""
        self._mutex.lock()
        self._abort_requested = True
        self._is_paused = False  # Unblock if paused
        self._mutex.unlock()
        self._pause_condition.wakeAll()
        # Also wake the confirmation wait
        self._confirm_condition.wakeAll()
        logger.info("Scan abort requested.")

    @property
    def is_running(self) -> bool:
        """Whether a scan is currently in progress."""
        return self._is_running

    @property
    def is_paused(self) -> bool:
        """Whether the scan is paused."""
        return self._is_paused

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _update_eta(self, completed: int, total: int):
        """Compute and emit estimated time remaining."""
        if completed == 0:
            return

        elapsed = time.monotonic() - self._scan_start_time
        avg_per_tile = elapsed / completed
        remaining_tiles = total - completed
        eta_s = avg_per_tile * remaining_tiles

        self.eta_updated.emit(eta_s)

    def _check_abort(self) -> bool:
        """Check if abort was requested. Emits scan_aborted if so."""
        self._mutex.lock()
        aborted = self._abort_requested
        self._mutex.unlock()

        if aborted:
            self._is_running = False
            logger.info("Scan aborted by user.")
            self.scan_aborted.emit()
            return True
        return False

    def _check_pause(self):
        """Block if pause was requested, until resume or abort."""
        self._mutex.lock()
        while self._is_paused and not self._abort_requested:
            self.progress_updated.emit(-1, -1, "Scan paused...")
            self._pause_condition.wait(self._mutex)
        self._mutex.unlock()


class ScanWorker(QtCore.QThread):
    """
    Worker thread that runs the ScanCoordinator.

    Usage
    -----
    ```python
    coordinator = ScanCoordinator()
    coordinator.configure(config, xy, camera)

    worker = ScanWorker(coordinator)
    # Connect signals...
    worker.start()
    ```
    """

    def __init__(self, coordinator: ScanCoordinator, parent=None):
        super().__init__(parent)
        self._coordinator = coordinator

    def run(self):
        """Thread entry point — runs the scan."""
        self._coordinator.run_scan()
