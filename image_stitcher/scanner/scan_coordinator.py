"""
Scan coordinator - orchestrates XY movement, camera capture, and stitching.

Runs the grid scan in a QThread, emitting Qt signals for GUI integration
(progress updates, preview images, completion/error notifications).
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
from ..stitching.compositor import Compositor
from ..stitching.feature_matcher import FeatureMatcher
from ..utils.image_io import save_both
from .grid_scanner import GridScanner

logger = logging.getLogger(__name__)


class ScanCoordinator(QtCore.QObject):
    """
    Coordinates the full grid scan pipeline.

    Runs in a worker thread and communicates with the GUI via Qt signals.
    Orchestrates: GridScanner (path) -> XYZ movement -> CameraAdapter (capture)
    -> FeatureMatcher (alignment) -> Compositor (stitching).

    Signals
    -------
    progress_updated(int, int, str)
        (current_tile, total_tiles, status_message)
    preview_ready(np.ndarray)
        Emitted when a new preview image is available (uint8).
    tile_captured(int, int, int)
        (row, col, tile_index) emitted after each tile is captured and placed.
    scan_finished(str)
        Emitted when the scan completes successfully. Carries the output path.
    scan_error(str)
        Emitted when an unrecoverable error occurs.
    scan_aborted()
        Emitted when the scan is aborted by the user.
    position_updated(float, float, float)
        (x_um, y_um, z_um) current platform position.
    eta_updated(float)
        Estimated time remaining in seconds.
    """

    progress_updated = QtCore.Signal(int, int, str)
    preview_ready = QtCore.Signal(object)  # np.ndarray
    tile_captured = QtCore.Signal(int, int, int)
    scan_finished = QtCore.Signal(str)
    scan_error = QtCore.Signal(str)
    scan_aborted = QtCore.Signal()
    position_updated = QtCore.Signal(float, float, float)
    eta_updated = QtCore.Signal(float)

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)

        self._config: Optional[ScanConfig] = None
        self._xy: Optional[XYTable] = None  # XY table instance
        self._camera: Optional[CameraAdapter] = None
        self._compositor: Optional[Compositor] = None
        self._feature_matcher: Optional[FeatureMatcher] = None
        self._grid_scanner: Optional[GridScanner] = None

        # State control
        self._is_running = False
        self._is_paused = False
        self._abort_requested = False
        self._mutex = QtCore.QMutex()
        self._pause_condition = QtCore.QWaitCondition()

        # Tile image cache for feature matching with neighbors
        self._tile_cache: dict[tuple[int, int], np.ndarray] = {}

        # Timing
        self._scan_start_time = 0.0
        self._tile_times: list[float] = []

        # Preview update interval (don't update every single tile for large grids)
        self._preview_interval = 1  # Update preview every N tiles

    def configure(self, config: ScanConfig, xy: XYTable, camera: CameraAdapter):
        """
        Set up the coordinator with all required components.

        Parameters
        ----------
        config : ScanConfig
            Scan configuration.
        xy : XYTable
            XY table controller (standalone, no xyz_table dependency).
        camera : CameraAdapter
            Camera adapter instance (should already be opened and configured).
        """
        self._config = config
        self._xy = xy
        self._camera = camera

        # Create sub-components
        self._grid_scanner = GridScanner(config)
        self._compositor = Compositor(config)
        self._feature_matcher = FeatureMatcher(
            method=config.matching_method,
            max_features=2000,
        )

        # Set preview update interval based on grid size
        total = self._grid_scanner.total_positions
        if total > 100:
            self._preview_interval = max(1, total // 50)
        elif total > 20:
            self._preview_interval = 2
        else:
            self._preview_interval = 1

        logger.info(
            f"Coordinator configured: {config.num_rows}x{config.num_cols} grid, "
            f"{total} tiles, preview every {self._preview_interval} tiles"
        )

    @QtCore.Slot()
    def run_scan(self):
        """
        Execute the full grid scan. Should be called from a worker thread.

        This is the main entry point — connect this to QThread.started or
        call from a worker.
        """
        if self._config is None or self._xy is None or self._camera is None:
            self.scan_error.emit("Coordinator not configured. Call configure() first.")
            return

        self._is_running = True
        self._abort_requested = False
        self._is_paused = False
        self._tile_cache.clear()
        self._tile_times.clear()
        self._scan_start_time = time.monotonic()

        config = self._config
        grid = self._grid_scanner
        total = grid.total_positions

        logger.info(f"Scan started: {total} tiles")
        self.progress_updated.emit(0, total, "Starting scan...")

        try:
            # Move Z axis to configured position first
            self._move_z(config.z_position)

            for idx, (row, col, x_um, y_um) in enumerate(grid.positions):
                # --- Check abort ---
                if self._check_abort():
                    return

                # --- Check pause ---
                self._check_pause()

                tile_start = time.monotonic()

                # --- Move XY ---
                status = f"Moving to tile ({row},{col}) [{idx + 1}/{total}]"
                self.progress_updated.emit(idx, total, status)
                self._move_xy(x_um, y_um)
                self.position_updated.emit(x_um, y_um, config.z_position)

                # --- Settle ---
                if config.settle_time_s > 0:
                    time.sleep(config.settle_time_s)

                # --- Check abort after move ---
                if self._check_abort():
                    return

                # --- Capture ---
                status = f"Capturing tile ({row},{col}) [{idx + 1}/{total}]"
                self.progress_updated.emit(idx, total, status)
                image = self._camera.capture_single()

                # --- Save individual tile if requested ---
                if config.save_individual_tiles and config.output_directory:
                    self._save_tile(image, row, col)

                # --- Feature matching for alignment correction ---
                precise_offset = self._compute_alignment(row, col, image)

                # --- Place tile on compositor ---
                self._compositor.add_tile(row, col, image, precise_offset)

                # --- Cache tile for neighbor matching ---
                self._tile_cache[(row, col)] = image
                self._prune_tile_cache(row, col)

                # --- Emit tile captured signal ---
                self.tile_captured.emit(row, col, idx)

                # --- Update timing ---
                tile_elapsed = time.monotonic() - tile_start
                self._tile_times.append(tile_elapsed)
                self._update_eta(idx + 1, total)

                # --- Emit preview ---
                if (idx + 1) % self._preview_interval == 0 or idx == total - 1:
                    preview = self._compositor.get_current_preview(scale=0.25)
                    self.preview_ready.emit(preview)

                self.progress_updated.emit(idx + 1, total, f"Tile ({row},{col}) done")

            # --- Finalize ---
            self.progress_updated.emit(total, total, "Finalizing composite...")
            result = self._compositor.finalize()

            # Save output
            output_path = self._save_output(result)

            self._is_running = False
            self.scan_finished.emit(output_path)
            logger.info(f"Scan completed: {output_path}")

        except Exception as e:
            self._is_running = False
            error_msg = f"Scan failed: {e}"
            logger.exception(error_msg)
            self.scan_error.emit(error_msg)

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

    def _move_xy(self, x_um: float, y_um: float):
        """Move the XY table to the given position (blocking)."""
        self._xy.move_to(x_um, y_um)

    def _move_z(self, z_um: float):
        """No-op: Z axis is not supported in this configuration."""
        logger.debug("Z axis not supported, skipping Z move.")

    def _compute_alignment(
        self, row: int, col: int, image: np.ndarray
    ) -> Optional[tuple[float, float]]:
        """
        Compute alignment offset by feature matching against a neighbor tile.

        Tries horizontal neighbor first (same row, previous col), then
        vertical neighbor (previous row, same col). Returns None if matching
        fails and fallback_to_position is True (uses nominal position).

        Returns
        -------
        Optional[tuple[float, float]]
            (dx, dy) correction in pixels from nominal position, or None.
        """
        config = self._config
        overlap = (config.overlap_pixels_x, config.overlap_pixels_y)

        # Determine which neighbor to match against
        neighbor_key = None
        expected_offset = None

        # Prefer horizontal neighbor (for serpentine, previous tile in row)
        if col > 0 and (row, col - 1) in self._tile_cache:
            neighbor_key = (row, col - 1)
            # Expected: new tile is shifted right by step_x pixels
            step_x_px = int(config.image_width * (1.0 - config.overlap_ratio))
            expected_offset = (float(step_x_px), 0.0)
        elif col < config.num_cols - 1 and (row, col + 1) in self._tile_cache:
            # Reverse direction in serpentine
            neighbor_key = (row, col + 1)
            step_x_px = int(config.image_width * (1.0 - config.overlap_ratio))
            expected_offset = (float(-step_x_px), 0.0)

        # Fallback: try vertical neighbor
        if neighbor_key is None and row > 0 and (row - 1, col) in self._tile_cache:
            neighbor_key = (row - 1, col)
            step_y_px = int(config.image_height * (1.0 - config.overlap_ratio))
            expected_offset = (0.0, float(step_y_px))

        if neighbor_key is None:
            # First tile or no neighbor available
            return None

        ref_image = self._tile_cache[neighbor_key]

        result = self._feature_matcher.compute_offset(
            img_ref=ref_image,
            img_new=image,
            expected_offset=expected_offset,
            overlap_pixels=overlap,
        )

        if result is not None:
            # Convert absolute offset to correction relative to nominal position
            dx_correction = result[0] - expected_offset[0]
            dy_correction = result[1] - expected_offset[1]
            logger.debug(
                f"Tile ({row},{col}): alignment correction "
                f"({dx_correction:.1f}, {dy_correction:.1f}) px"
            )
            return (dx_correction, dy_correction)
        else:
            if config.fallback_to_position:
                logger.info(
                    f"Tile ({row},{col}): feature matching failed, "
                    f"using motor position (nominal placement)"
                )
                return None
            else:
                logger.warning(
                    f"Tile ({row},{col}): feature matching failed, no fallback enabled"
                )
                return None

    def _prune_tile_cache(self, current_row: int, current_col: int):
        """
        Remove tiles from cache that are no longer needed for matching.

        We only need tiles from the current row (for horizontal matching)
        and the previous row (for vertical matching of the next row).
        """
        keys_to_remove = []
        for r, c in self._tile_cache:
            if r < current_row - 1:
                keys_to_remove.append((r, c))
        for key in keys_to_remove:
            del self._tile_cache[key]

    def _save_tile(self, image: np.ndarray, row: int, col: int):
        """Save an individual tile image."""
        tile_dir = os.path.join(self._config.output_directory, "tiles")
        os.makedirs(tile_dir, exist_ok=True)
        filepath = os.path.join(tile_dir, f"tile_r{row:03d}_c{col:03d}")
        save_both(image, filepath)

    def _save_output(self, result: np.ndarray) -> str:
        """Save the final composite image and return the output path."""
        config = self._config
        if config.output_directory:
            output_dir = config.output_directory
        else:
            output_dir = os.path.join(os.getcwd(), "stitcher_output")

        os.makedirs(output_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"composite_{timestamp}"
        filepath_base = os.path.join(output_dir, base_name)

        results = save_both(result, filepath_base)
        logger.info(f"Output saved: TIFF={results['tiff']}, PNG={results['png']}")

        return filepath_base

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
    coordinator.configure(config, xyz, camera)

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
