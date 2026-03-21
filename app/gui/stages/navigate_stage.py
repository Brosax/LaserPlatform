"""Navigate stage: panorama-based chip navigation with affine calibration."""

import logging
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtWidgets

from image_stitcher.acquisition.camera_adapter import LiveFeedWorker
from image_stitcher.acquisition.xy_table import XYTable
from image_stitcher.gui.preview_widget import PreviewWidget
from image_stitcher.gui.xy_control_widget import XYControlWidget

from chip_navigator.gui.calibration_widget import CalibrationWidget
from chip_navigator.gui.panorama_map_widget import PanoramaMapWidget
from chip_navigator.mapping.calibration import AffineCalibration

from ...session import AppSession
from ...i18n import tr

logger = logging.getLogger(__name__)


class _MoveWorker(QtCore.QThread):
    """Runs a blocking move in a background thread."""

    finished_ok = QtCore.Signal()
    error_occurred = QtCore.Signal(str)

    def __init__(self, xy: XYTable, x_um: float, y_um: float, parent=None):
        super().__init__(parent)
        self._xy = xy
        self._x = x_um
        self._y = y_um

    def run(self):
        try:
            self._xy.move_to(self._x, self._y)
            self.finished_ok.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))


class NavigateStage(QtWidgets.QWidget):
    """Third stage: panorama-based chip navigation.

    Reuses CalibrationWidget, PanoramaMapWidget, PreviewWidget, and
    XYControlWidget. Extracts the calibration/navigation logic from
    ChipNavigatorWindow.
    """

    def __init__(self, session: AppSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._calibration = AffineCalibration()

        self._live_worker: Optional[LiveFeedWorker] = None
        self._move_worker: Optional[_MoveWorker] = None
        self._pending_pixel: Optional[tuple[float, float]] = None
        self._pending_target_stage: Optional[tuple[float, float]] = None

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # Left: calibration + XY control
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._cal_widget = CalibrationWidget()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self._cal_widget)
        scroll.setWidgetResizable(True)
        left_layout.addWidget(scroll, stretch=1)

        self._xy_control = XYControlWidget()
        left_layout.addWidget(self._xy_control, stretch=0)

        left_panel.setMinimumWidth(300)
        left_panel.setMaximumWidth(450)
        splitter.addWidget(left_panel)

        # Center: panorama map
        self._panorama_widget = PanoramaMapWidget()
        splitter.addWidget(self._panorama_widget)

        # Right: live camera preview
        self._preview_widget = PreviewWidget()
        self._preview_widget.setMinimumWidth(300)
        self._preview_widget.setMaximumWidth(700)
        splitter.addWidget(self._preview_widget)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

        main_layout.addWidget(splitter, stretch=1)

    def _connect_signals(self):
        self._panorama_widget.point_clicked.connect(self._on_panorama_clicked)
        self._cal_widget.record_requested.connect(self._on_record_point)
        self._cal_widget.solve_requested.connect(self._on_solve)
        self._cal_widget.clear_requested.connect(self._on_clear_calibration)
        self._cal_widget.remove_requested.connect(self._on_remove_point)
        self._cal_widget.save_requested.connect(self._on_save_calibration)
        self._cal_widget.load_requested.connect(self._on_load_calibration)
        self._cal_widget.mode_changed.connect(self._on_mode_changed)
        self._cal_widget.move_button.clicked.connect(self._on_move_to_target)
        self._xy_control.position_changed.connect(self._on_stage_position_changed)

    # ------------------------------------------------------------------ #
    #  Hardware sync
    # ------------------------------------------------------------------ #

    def on_hardware_changed(self):
        """Called when hardware connection changes."""
        xy = self._session.xy_table
        self._xy_control.set_xy_table(xy)

        cam = self._session.camera
        if cam is not None and cam.is_open:
            self._start_live_feed()
        else:
            self._stop_live_feed()

    # ------------------------------------------------------------------ #
    #  Panorama
    # ------------------------------------------------------------------ #

    def load_panorama(self, path: str):
        """Load a panorama image file."""
        self._panorama_widget.load_image(path)

    @QtCore.Slot(float, float)
    def _on_panorama_clicked(self, u: float, v: float):
        mode = self._cal_widget.current_mode
        if mode == "calibration":
            self._pending_pixel = (u, v)
            self._cal_widget.set_pending_pixel(u, v)
        elif mode == "navigation":
            if not self._calibration.is_solved:
                QtWidgets.QMessageBox.warning(
                    self, tr("nav.not_calibrated"), tr("nav.not_calibrated_msg")
                )
                return
            try:
                sx, sy = self._calibration.pixel_to_stage(u, v)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, tr("nav.transform_error"), str(e))
                return
            self._pending_target_stage = (sx, sy)
            self._cal_widget.set_target_info(u, v, sx, sy)
            self._panorama_widget.set_target_point((u, v))

    # ------------------------------------------------------------------ #
    #  Calibration workflow
    # ------------------------------------------------------------------ #

    @QtCore.Slot()
    def _on_record_point(self):
        if self._pending_pixel is None:
            QtWidgets.QMessageBox.warning(self, tr("nav.no_pixel"), tr("nav.no_pixel_msg"))
            return
        xy = self._session.xy_table
        if xy is None:
            QtWidgets.QMessageBox.warning(self, tr("nav.not_connected"), tr("nav.not_connected_xy"))
            return
        try:
            x_um, y_um = xy.update_position()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, tr("nav.read_failed"), str(e))
            return

        u, v = self._pending_pixel
        self._calibration.add_point(u, v, x_um, y_um)
        self._pending_pixel = None
        self._cal_widget.clear_pending_pixel()
        self._refresh_calibration_ui()

    @QtCore.Slot()
    def _on_solve(self):
        try:
            result = self._calibration.solve()
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, tr("nav.calib_error"), str(e))
            return
        self._refresh_calibration_ui()
        QtWidgets.QMessageBox.information(
            self,
            tr("nav.calib_done"),
            tr("nav.calib_done_msg").format(
                result.num_points,
                result.rmse,
                max(result.per_point_errors),
            ),
        )

    @QtCore.Slot(int)
    def _on_remove_point(self, index: int):
        self._calibration.remove_point(index)
        self._refresh_calibration_ui()

    @QtCore.Slot()
    def _on_clear_calibration(self):
        reply = QtWidgets.QMessageBox.question(
            self, tr("nav.clear_title"), tr("nav.clear_msg"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._calibration.clear_points()
            self._refresh_calibration_ui()
            self._panorama_widget.clear_overlays()

    def _refresh_calibration_ui(self):
        self._cal_widget.update_points_table(self._calibration)
        self._cal_widget.update_status(self._calibration)
        pixel_points = [(pt.pixel_u, pt.pixel_v) for pt in self._calibration.points]
        self._panorama_widget.set_calibration_points(pixel_points)

    @QtCore.Slot()
    def _on_save_calibration(self):
        if self._calibration.num_points == 0:
            QtWidgets.QMessageBox.information(self, tr("nav.no_data"), tr("nav.no_points"))
            return
        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, tr("nav.save_calib"), "calibration.json", "JSON (*.json)"
        )
        if filepath:
            try:
                self._calibration.save(filepath)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, tr("nav.save_failed"), str(e))

    @QtCore.Slot()
    def _on_load_calibration(self):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, tr("nav.load_calib"), "", "JSON (*.json)"
        )
        if filepath:
            try:
                self._calibration.load(filepath)
                self._refresh_calibration_ui()
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, tr("nav.load_failed"), str(e))

    @QtCore.Slot(str)
    def _on_mode_changed(self, mode: str):
        if mode == "navigation":
            self._pending_pixel = None
            self._cal_widget.clear_pending_pixel()
        else:
            self._pending_target_stage = None
            self._cal_widget.clear_target_info()
            self._panorama_widget.set_target_point(None)

    # ------------------------------------------------------------------ #
    #  Navigation / move
    # ------------------------------------------------------------------ #

    @QtCore.Slot()
    def _on_move_to_target(self):
        if self._pending_target_stage is None:
            return
        xy = self._session.xy_table
        if xy is None:
            QtWidgets.QMessageBox.warning(self, tr("nav.not_connected"), tr("nav.not_connected_xy"))
            return
        if self._move_worker is not None and self._move_worker.isRunning():
            return

        sx, sy = self._pending_target_stage

        if self._cal_widget.confirm_before_move:
            reply = QtWidgets.QMessageBox.question(
                self,
                tr("nav.confirm_move"),
                tr("nav.confirm_move_msg").format(sx, sy),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        self._move_worker = _MoveWorker(xy, sx, sy, parent=self)
        self._move_worker.finished_ok.connect(self._on_move_finished)
        self._move_worker.error_occurred.connect(self._on_move_error)
        self._cal_widget.move_button.setEnabled(False)
        self._move_worker.start()

    @QtCore.Slot()
    def _on_move_finished(self):
        self._cal_widget.move_button.setEnabled(True)
        self._move_worker = None
        xy = self._session.xy_table
        if xy is not None:
            try:
                x, y = xy.update_position()
                self._on_stage_position_changed(x, y)
            except Exception:
                pass
        self._xy_control._refresh_position()

    @QtCore.Slot(str)
    def _on_move_error(self, msg: str):
        self._cal_widget.move_button.setEnabled(True)
        self._move_worker = None
        QtWidgets.QMessageBox.critical(self, tr("nav.move_failed"), msg)

    @QtCore.Slot(float, float)
    def _on_stage_position_changed(self, x_um: float, y_um: float):
        if self._calibration.is_solved:
            try:
                pu, pv = self._calibration.stage_to_pixel(x_um, y_um)
                self._panorama_widget.set_stage_position((pu, pv))
            except Exception:
                self._panorama_widget.set_stage_position(None)
        else:
            self._panorama_widget.set_stage_position(None)

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
    #  Cleanup
    # ------------------------------------------------------------------ #

    def stop_all(self):
        """Stop live feed and pending moves."""
        self._stop_live_feed()
        if self._move_worker is not None and self._move_worker.isRunning():
            self._move_worker.wait(3000)
