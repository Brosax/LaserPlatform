"""Scan stage: configures and runs grid scanning using shared hardware."""

import logging
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtWidgets

from image_stitcher.config import ScanConfig
from ...i18n import tr
from image_stitcher.acquisition.camera_adapter import LiveFeedWorker
from image_stitcher.scanner.scan_coordinator import ScanCoordinator, ScanWorker
from image_stitcher.utils.image_io import save_png_8bit
from image_stitcher.gui.scan_config_widget import ScanConfigWidget
from image_stitcher.gui.preview_widget import PreviewWidget
from image_stitcher.gui.progress_widget import ProgressWidget
from image_stitcher.gui.xy_control_widget import XYControlWidget

from ...session import AppSession

logger = logging.getLogger(__name__)


class ScanStage(QtWidgets.QWidget):
    """First stage: S-pattern grid scanning.

    Reuses all widgets from image_stitcher and extracts the scan
    orchestration logic from its MainWindow.

    Signals
    -------
    scan_finished(str)
        Emitted when scan completes. Carries the output directory path.
    """

    scan_finished = QtCore.Signal(str)

    def __init__(self, session: AppSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._coordinator: Optional[ScanCoordinator] = None
        self._scan_worker: Optional[ScanWorker] = None
        self._live_worker: Optional[LiveFeedWorker] = None

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # Left: config + XY control
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._config_widget = ScanConfigWidget()
        left_layout.addWidget(self._config_widget, stretch=1)

        self._xy_control = XYControlWidget()
        left_layout.addWidget(self._xy_control, stretch=0)

        left_panel.setMinimumWidth(450)
        left_panel.setMaximumWidth(700)
        splitter.addWidget(left_panel)

        # Right: preview
        self._preview_widget = PreviewWidget()
        splitter.addWidget(self._preview_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter, stretch=1)

        # Bottom: progress
        self._progress_widget = ProgressWidget()
        main_layout.addWidget(self._progress_widget)

    def _connect_signals(self):
        self._config_widget.config_changed.connect(self._on_config_changed)
        self._config_widget.mark_corner_requested.connect(self._on_mark_corner)
        self._progress_widget.start_requested.connect(self._on_start_scan)
        self._progress_widget.pause_requested.connect(self._on_pause_scan)
        self._progress_widget.resume_requested.connect(self._on_resume_scan)
        self._progress_widget.abort_requested.connect(self._on_abort_scan)

    # ------------------------------------------------------------------ #
    #  Hardware sync
    # ------------------------------------------------------------------ #

    def on_hardware_changed(self):
        """Called by main window when hardware connection changes."""
        xy = self._session.xy_table
        self._xy_control.set_xy_table(xy)

        # Stop feed if camera disconnected; starting is handled by on_stage_enter
        cam = self._session.camera
        if cam is None or not cam.is_open:
            self._stop_live_feed()

    def on_stage_enter(self):
        """Called when this stage becomes the active visible stage."""
        cam = self._session.camera
        if cam is not None and cam.is_open:
            self._start_live_feed()

    def on_stage_leave(self):
        """Called when this stage is hidden (switching to another stage)."""
        self._stop_live_feed()

    # ------------------------------------------------------------------ #
    #  Config
    # ------------------------------------------------------------------ #

    def _on_config_changed(self, config: ScanConfig):
        cam = self._session.camera
        if cam is not None and cam.is_open:
            try:
                cam.configure(
                    exposure_us=config.exposure_time_us,
                    auto_exposure=config.auto_exposure,
                )
            except Exception as e:
                logger.warning(f"Failed to apply camera config: {e}")

    def _on_mark_corner(self, corner_index: int):
        xy = self._session.xy_table
        if xy is None:
            QtWidgets.QMessageBox.warning(self, tr("scan.not_connected"), tr("scan.not_connected_xy"))
            return
        try:
            x_um, y_um = xy.update_position()
            self._config_widget.set_corner(corner_index, x_um, y_um)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, tr("scan.read_pos_failed"), str(e))

    # ------------------------------------------------------------------ #
    #  Live camera feed
    # ------------------------------------------------------------------ #

    def _start_live_feed(self):
        cam = self._session.camera
        if cam is None or not cam.is_open:
            return
        if self._live_worker is not None and self._live_worker.is_streaming:
            return
        self._live_worker = LiveFeedWorker(cam)
        self._live_worker.frame_ready.connect(self._on_live_frame)
        self._live_worker.error_occurred.connect(self._on_live_error)
        self._live_worker.start()

    def _stop_live_feed(self):
        if self._live_worker is None:
            return
        self._live_worker.stop()
        self._live_worker.wait(3000)
        self._live_worker = None

    @QtCore.Slot(object)
    def _on_live_frame(self, frame: np.ndarray):
        self._preview_widget.update_live_frame(frame)

    @QtCore.Slot(str)
    def _on_live_error(self, msg: str):
        logger.error(f"Live feed error: {msg}")
        self._stop_live_feed()

    # ------------------------------------------------------------------ #
    #  Scan control
    # ------------------------------------------------------------------ #

    def _on_start_scan(self):
        config = self._config_widget.get_config()
        errors = config.validate()
        if errors:
            QtWidgets.QMessageBox.warning(
                self, tr("scan.config_error"), "\n".join(errors)
            )
            return

        xy = self._session.xy_table
        cam = self._session.camera
        if xy is None:
            QtWidgets.QMessageBox.warning(self, tr("scan.not_connected"), tr("scan.not_connected_xy"))
            return
        if cam is None or not cam.is_open:
            QtWidgets.QMessageBox.warning(self, tr("scan.not_connected"), tr("scan.not_connected_cam"))
            return

        self._stop_live_feed()

        cam.configure(
            exposure_us=config.exposure_time_us,
            auto_exposure=config.auto_exposure,
        )

        self._coordinator = ScanCoordinator()
        self._coordinator.configure(config, xy, cam)

        self._coordinator.progress_updated.connect(self._on_progress_updated)
        self._coordinator.tile_captured.connect(self._on_tile_captured)
        self._coordinator.scan_finished.connect(self._on_scan_finished)
        self._coordinator.scan_error.connect(self._on_scan_error)
        self._coordinator.scan_aborted.connect(self._on_scan_aborted)
        self._coordinator.position_updated.connect(self._on_position_updated)
        self._coordinator.eta_updated.connect(self._on_eta_updated)
        self._coordinator.confirm_capture_requested.connect(
            self._on_confirm_capture_requested
        )

        self._scan_worker = ScanWorker(self._coordinator)
        self._scan_worker.finished.connect(self._on_worker_finished)

        self._config_widget.set_enabled(False)
        self._xy_control.setEnabled(False)
        self._progress_widget.reset()
        self._progress_widget.set_state("running")
        self._preview_widget.clear()

        self._scan_worker.start()

    def _on_pause_scan(self):
        if self._coordinator:
            self._coordinator.pause()
            self._progress_widget.set_state("paused")

    def _on_resume_scan(self):
        if self._coordinator:
            self._coordinator.resume()
            self._progress_widget.set_state("running")

    def _on_abort_scan(self):
        if self._coordinator:
            self._coordinator.abort()

    # ------------------------------------------------------------------ #
    #  Coordinator signal handlers
    # ------------------------------------------------------------------ #

    @QtCore.Slot(int, int, str)
    def _on_progress_updated(self, current: int, total: int, status: str):
        self._progress_widget.update_progress(current, total, status)

    @QtCore.Slot(int, int, int)
    def _on_tile_captured(self, row: int, col: int, idx: int):
        logger.info(f"Tile captured: row={row}, col={col}, idx={idx}")

    @QtCore.Slot(int, int, float, float)
    def _on_confirm_capture_requested(
        self, row: int, col: int, x_um: float, y_um: float
    ):
        pos_text = f"Position ({row},{col}) - X={x_um:.1f}, Y={y_um:.1f} um"
        self._preview_widget.set_position_text(pos_text)
        self._start_live_feed()

        msgbox = QtWidgets.QMessageBox(self)
        msgbox.setWindowTitle(tr("scan.confirm_title"))
        msgbox.setText(tr("scan.confirm_text").format(row, col, x_um, y_um))
        msgbox.setIcon(QtWidgets.QMessageBox.Icon.Question)
        capture_btn = msgbox.addButton(tr("scan.capture"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        skip_btn = msgbox.addButton(tr("scan.skip"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msgbox.setDefaultButton(capture_btn)
        msgbox.exec()

        self._stop_live_feed()

        if msgbox.clickedButton() == capture_btn:
            self._coordinator.confirm_capture()
        else:
            self._coordinator.skip_capture()

        self._preview_widget.set_position_text("")

    @QtCore.Slot(str)
    def _on_scan_finished(self, output_path: str):
        self._stop_live_feed()
        self._progress_widget.set_state("finished")
        self._config_widget.set_enabled(True)
        self._xy_control.setEnabled(True)
        self._start_live_feed()
        self.scan_finished.emit(output_path)

    @QtCore.Slot(str)
    def _on_scan_error(self, error_msg: str):
        self._stop_live_feed()
        self._progress_widget.set_state("error")
        self._config_widget.set_enabled(True)
        self._xy_control.setEnabled(True)
        self._start_live_feed()
        QtWidgets.QMessageBox.critical(self, tr("scan.error_title"), error_msg)

    @QtCore.Slot()
    def _on_scan_aborted(self):
        self._stop_live_feed()
        self._progress_widget.set_state("aborted")
        self._config_widget.set_enabled(True)
        self._xy_control.setEnabled(True)
        self._start_live_feed()

    @QtCore.Slot(float, float)
    def _on_position_updated(self, x_um: float, y_um: float):
        self._progress_widget.update_position(x_um, y_um)

    @QtCore.Slot(float)
    def _on_eta_updated(self, eta_s: float):
        self._progress_widget.update_eta(eta_s)

    def _on_worker_finished(self):
        self._scan_worker = None

    # ------------------------------------------------------------------ #
    #  Cleanup
    # ------------------------------------------------------------------ #

    def stop_all(self):
        """Stop any running scan and live feed. Called before closing."""
        if self._coordinator and self._coordinator.is_running:
            self._coordinator.abort()
            if self._scan_worker is not None:
                self._scan_worker.wait(5000)
        self._stop_live_feed()
