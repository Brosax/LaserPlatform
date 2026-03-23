"""
Chip Navigator main window.

Layout
------
+-------------------------------------------------------------+
| Menu Bar (Hardware | File | View)                           |
+------------------+------------------------+-----------------+
|                  |                        |                 |
| Calibration      |    Panorama Map        |  Camera Preview |
| Panel            |    (chip overview)     |  (live feed)    |
| (left sidebar)   |                        |                 |
|                  |                        |                 |
+------------------+------------------------+-----------------+
| Status Bar  (hardware status + position)                    |
+-------------------------------------------------------------+

Workflow
--------
1. Load a panorama image (File > Open Panorama or drag-drop)
2. Connect XY table and camera (Hardware menu)
3. Calibration mode:
   a. Click a recognisable feature on the panorama
   b. Manually jog the stage so the camera centers on that feature
   c. Click "Record Point" -> stores (pixel, stageXY) pair
   d. Repeat >= 3 times, then "Solve"
4. Switch to Navigation mode:
   a. Click any point on the panorama
   b. Computed target XY is shown; click "Move to Target"
   c. Stage moves; camera live view confirms position
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

# Ensure the project root is on sys.path so sibling packages are importable
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Reuse hardware adapters from image_stitcher
from image_stitcher.acquisition.camera_adapter import CameraAdapter, LiveFeedWorker
from image_stitcher.acquisition.smc100_axis import SMC100Axis
from image_stitcher.acquisition.xy_table import XYTable
from image_stitcher.gui.preview_widget import PreviewWidget
from image_stitcher.gui.xy_control_widget import XYControlWidget

from ..mapping.calibration import AffineCalibration
from .calibration_widget import CalibrationWidget
from .panorama_map_widget import PanoramaMapWidget

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  XY Connection Dialog (same as image_stitcher)
# ------------------------------------------------------------------ #


class XYConnectDialog(QtWidgets.QDialog):
    """Dialog for connecting the XY table (COM port + addresses)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect XY Table")
        self.setMinimumWidth(380)

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()

        # COM port
        port_row = QtWidgets.QHBoxLayout()
        self._port = QtWidgets.QComboBox()
        self._port.setEditable(True)
        port_row.addWidget(self._port, stretch=1)
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.setMaximumWidth(60)
        refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(refresh_btn)
        form.addRow("COM Port:", port_row)

        self._x_addr = QtWidgets.QSpinBox()
        self._x_addr.setRange(0, 31)
        self._x_addr.setValue(1)
        form.addRow("X Address:", self._x_addr)

        self._y_addr = QtWidgets.QSpinBox()
        self._y_addr.setRange(0, 31)
        self._y_addr.setValue(2)
        form.addRow("Y Address:", self._y_addr)

        self._timeout = QtWidgets.QDoubleSpinBox()
        self._timeout.setRange(0.1, 60.0)
        self._timeout.setValue(1.0)
        self._timeout.setSuffix(" s")
        form.addRow("Timeout:", self._timeout)

        layout.addLayout(form)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        connect_btn = QtWidgets.QPushButton("Connect")
        connect_btn.setDefault(True)
        connect_btn.clicked.connect(self.accept)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(connect_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self._refresh_ports()

    def _refresh_ports(self):
        current = self._port.currentText()
        self._port.clear()
        try:
            import serial.tools.list_ports

            for info in serial.tools.list_ports.comports():
                self._port.addItem(f"{info.device} - {info.description}", info.device)
        except ImportError:
            pass
        idx = self._port.findText(current)
        if idx >= 0:
            self._port.setCurrentIndex(idx)

    def create_xy_table(self) -> XYTable:
        data = self._port.currentData()
        port = data if data else self._port.currentText().split(" - ")[0].strip()
        timeout = self._timeout.value()
        x = SMC100Axis(port, self._x_addr.value(), timeout)
        y = SMC100Axis(port, self._y_addr.value(), timeout)
        return XYTable(x, y)


# ------------------------------------------------------------------ #
#  Move Worker
# ------------------------------------------------------------------ #


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


# ------------------------------------------------------------------ #
#  Main Window
# ------------------------------------------------------------------ #


class ChipNavigatorWindow(QtWidgets.QMainWindow):
    """
    Main window for the Chip Navigator application.
    """

    def __init__(
        self,
        xy_table: Optional[XYTable] = None,
        camera: Optional[CameraAdapter] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)

        self._xy: Optional[XYTable] = xy_table
        self._camera: Optional[CameraAdapter] = camera
        self._calibration = AffineCalibration()

        self._live_worker: Optional[LiveFeedWorker] = None
        self._move_worker: Optional[_MoveWorker] = None

        # Pending calibration pixel (from clicking on panorama)
        self._pending_pixel: Optional[tuple[float, float]] = None
        # Pending navigation target in stage coords
        self._pending_target_stage: Optional[tuple[float, float]] = None

        self._setup_ui()
        self._setup_menu()
        self._connect_signals()

        self.setWindowTitle("Chip Navigator")
        self.resize(1400, 900)

        self._update_hardware_status()
        if self._xy is not None:
            self._xy_control.set_xy_table(self._xy)

    # ================================================================== #
    #  UI setup
    # ================================================================== #

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # --- Main splitter: [left sidebar | panorama | right panel] ---
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # Left: calibration panel + XY control
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Wrap calibration widget in a scroll area
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

        splitter.setStretchFactor(0, 0)  # left: fixed
        splitter.setStretchFactor(1, 3)  # center: panorama gets most space
        splitter.setStretchFactor(2, 1)  # right: camera preview

        main_layout.addWidget(splitter, stretch=1)

        # --- Status bar ---
        self._hw_status_label = QtWidgets.QLabel("Hardware: Not connected")
        self.statusBar().addPermanentWidget(self._hw_status_label)

        self._rotation_label = QtWidgets.QLabel("Rot: 0\u00b0")
        self.statusBar().addPermanentWidget(self._rotation_label)

    def _setup_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        open_action = file_menu.addAction("Open Panorama Image...")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_panorama)

        file_menu.addSeparator()

        save_cal_action = file_menu.addAction("Save Calibration...")
        save_cal_action.setShortcut("Ctrl+S")
        save_cal_action.triggered.connect(self._on_save_calibration)

        load_cal_action = file_menu.addAction("Load Calibration...")
        load_cal_action.setShortcut("Ctrl+L")
        load_cal_action.triggered.connect(self._on_load_calibration)

        # Hardware menu
        hw_menu = menubar.addMenu("Hardware")

        self._connect_xy_action = hw_menu.addAction("Connect XY Table...")
        self._connect_xy_action.triggered.connect(self._on_connect_xy)

        self._disconnect_xy_action = hw_menu.addAction("Disconnect XY Table")
        self._disconnect_xy_action.triggered.connect(self._on_disconnect_xy)

        hw_menu.addSeparator()

        self._connect_camera_action = hw_menu.addAction("Connect Camera...")
        self._connect_camera_action.triggered.connect(self._on_connect_camera)

        self._disconnect_camera_action = hw_menu.addAction("Disconnect Camera")
        self._disconnect_camera_action.triggered.connect(self._on_disconnect_camera)

        # View menu
        view_menu = menubar.addMenu("View")
        fit_action = view_menu.addAction("Fit Panorama")
        fit_action.setShortcut("Ctrl+F")
        fit_action.triggered.connect(self._panorama_widget._fit_to_view)

        view_menu.addSeparator()

        rotate_left_action = view_menu.addAction("Rotate Left 90\u00b0")
        rotate_left_action.setShortcut("Ctrl+[")
        rotate_left_action.triggered.connect(self._on_rotate_left)

        rotate_right_action = view_menu.addAction("Rotate Right 90\u00b0")
        rotate_right_action.setShortcut("Ctrl+]")
        rotate_right_action.triggered.connect(self._on_rotate_right)

        reset_rotation_action = view_menu.addAction("Reset Rotation")
        reset_rotation_action.setShortcut("Ctrl+0")
        reset_rotation_action.triggered.connect(self._on_reset_rotation)

    def _connect_signals(self):
        # Panorama clicks
        self._panorama_widget.point_clicked.connect(self._on_panorama_clicked)

        # Calibration panel
        self._cal_widget.record_requested.connect(self._on_record_point)
        self._cal_widget.solve_requested.connect(self._on_solve)
        self._cal_widget.clear_requested.connect(self._on_clear_calibration)
        self._cal_widget.remove_requested.connect(self._on_remove_point)
        self._cal_widget.save_requested.connect(self._on_save_calibration)
        self._cal_widget.load_requested.connect(self._on_load_calibration)
        self._cal_widget.mode_changed.connect(self._on_mode_changed)

        # Move button
        self._cal_widget.move_button.clicked.connect(self._on_move_to_target)

        # XY control position changes -> update stage marker
        self._xy_control.position_changed.connect(self._on_stage_position_changed)

    # ================================================================== #
    #  Panorama click handling
    # ================================================================== #

    @QtCore.Slot(float, float)
    def _on_panorama_clicked(self, u: float, v: float):
        """Handle a click on the panorama image."""
        mode = self._cal_widget.current_mode

        if mode == "calibration":
            # Store pending pixel for next "Record Point"
            self._pending_pixel = (u, v)
            self._cal_widget.set_pending_pixel(u, v)
            logger.info(f"Calibration: pixel selected at ({u:.1f}, {v:.1f})")

        elif mode == "navigation":
            if not self._calibration.is_solved:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Not Calibrated",
                    "Calibration has not been solved yet.\n\n"
                    "Switch to Calibration mode, add 3+ points, and solve.",
                )
                return

            # Compute stage target
            try:
                sx, sy = self._calibration.pixel_to_stage(u, v)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Transform Error", str(e))
                return

            self._pending_target_stage = (sx, sy)
            self._cal_widget.set_target_info(u, v, sx, sy)
            self._panorama_widget.set_target_point((u, v))
            logger.info(
                f"Navigation: target px({u:.0f},{v:.0f}) -> stage({sx:.1f},{sy:.1f}) um"
            )

    # ================================================================== #
    #  Calibration workflow
    # ================================================================== #

    @QtCore.Slot()
    def _on_record_point(self):
        """Record the current pixel + stage position as a calibration point."""
        if self._pending_pixel is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No Pixel Selected",
                "Click on the panorama image first to select a pixel.",
            )
            return

        if self._xy is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No XY Table",
                "XY table is not connected. Cannot read stage position.",
            )
            return

        try:
            x_um, y_um = self._xy.update_position()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Position Read Error", f"Failed to read position:\n{e}"
            )
            return

        u, v = self._pending_pixel
        self._calibration.add_point(u, v, x_um, y_um)
        self._pending_pixel = None
        self._cal_widget.clear_pending_pixel()

        self._refresh_calibration_ui()

        self.statusBar().showMessage(
            f"Point recorded: px({u:.0f},{v:.0f}) -> stage({x_um:.1f},{y_um:.1f}) um",
            5000,
        )

    @QtCore.Slot()
    def _on_solve(self):
        """Solve the affine calibration."""
        try:
            result = self._calibration.solve()
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "Calibration Error", str(e))
            return

        self._refresh_calibration_ui()

        QtWidgets.QMessageBox.information(
            self,
            "Calibration Solved",
            f"Affine calibration solved successfully.\n\n"
            f"Points: {result.num_points}\n"
            f"RMSE: {result.rmse:.2f} um\n"
            f"Max error: {max(result.per_point_errors):.2f} um",
        )

    @QtCore.Slot(int)
    def _on_remove_point(self, index: int):
        self._calibration.remove_point(index)
        self._refresh_calibration_ui()

    @QtCore.Slot()
    def _on_clear_calibration(self):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear Calibration",
            "Remove all calibration points?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._calibration.clear_points()
            self._refresh_calibration_ui()
            self._panorama_widget.clear_overlays()

    def _refresh_calibration_ui(self):
        """Sync calibration data to the UI widgets."""
        self._cal_widget.update_points_table(self._calibration)
        self._cal_widget.update_status(self._calibration)

        # Update panorama overlay markers
        pixel_points = [(pt.pixel_u, pt.pixel_v) for pt in self._calibration.points]
        self._panorama_widget.set_calibration_points(pixel_points)

    # ================================================================== #
    #  Navigation / move
    # ================================================================== #

    @QtCore.Slot()
    def _on_move_to_target(self):
        """Move the stage to the current navigation target."""
        if self._pending_target_stage is None:
            return
        if self._xy is None:
            QtWidgets.QMessageBox.warning(
                self, "No XY Table", "XY table is not connected."
            )
            return
        if self._move_worker is not None and self._move_worker.isRunning():
            return

        sx, sy = self._pending_target_stage

        # Optional confirmation
        if self._cal_widget.confirm_before_move:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm Move",
                f"Move stage to:\n\n  X = {sx:.1f} um\n  Y = {sy:.1f} um\n\nContinue?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        # Run move in background thread
        self._move_worker = _MoveWorker(self._xy, sx, sy, parent=self)
        self._move_worker.finished_ok.connect(self._on_move_finished)
        self._move_worker.error_occurred.connect(self._on_move_error)

        self._cal_widget.move_button.setEnabled(False)
        self.statusBar().showMessage(f"Moving to ({sx:.1f}, {sy:.1f}) um...", 0)
        self._move_worker.start()

    @QtCore.Slot()
    def _on_move_finished(self):
        self._cal_widget.move_button.setEnabled(True)
        self._move_worker = None

        # Refresh position display
        if self._xy is not None:
            try:
                x, y = self._xy.update_position()
                self._on_stage_position_changed(x, y)
                self.statusBar().showMessage(f"Arrived at ({x:.1f}, {y:.1f}) um", 5000)
            except Exception:
                pass

        # Refresh XY control
        self._xy_control._refresh_position()

    @QtCore.Slot(str)
    def _on_move_error(self, msg: str):
        self._cal_widget.move_button.setEnabled(True)
        self._move_worker = None
        QtWidgets.QMessageBox.critical(self, "Move Error", msg)
        self.statusBar().showMessage(f"Move failed: {msg}", 5000)

    @QtCore.Slot(float, float)
    def _on_stage_position_changed(self, x_um: float, y_um: float):
        """Update the stage position marker on the panorama."""
        if self._calibration.is_solved:
            try:
                pu, pv = self._calibration.stage_to_pixel(x_um, y_um)
                self._panorama_widget.set_stage_position((pu, pv))
            except Exception:
                self._panorama_widget.set_stage_position(None)
        else:
            self._panorama_widget.set_stage_position(None)

    @QtCore.Slot(str)
    def _on_mode_changed(self, mode: str):
        """Handle mode switch between calibration and navigation."""
        if mode == "navigation":
            self._pending_pixel = None
            self._cal_widget.clear_pending_pixel()
        else:
            self._pending_target_stage = None
            self._cal_widget.clear_target_info()
            self._panorama_widget.set_target_point(None)

    # ================================================================== #
    #  Rotation
    # ================================================================== #

    def _update_rotation_label(self):
        self._rotation_label.setText(
            f"Rot: {self._panorama_widget.rotation_degrees}\u00b0"
        )

    @QtCore.Slot()
    def _on_rotate_left(self):
        self._panorama_widget.rotate_left_90()
        self._update_rotation_label()

    @QtCore.Slot()
    def _on_rotate_right(self):
        self._panorama_widget.rotate_right_90()
        self._update_rotation_label()

    @QtCore.Slot()
    def _on_reset_rotation(self):
        self._panorama_widget.reset_rotation()
        self._update_rotation_label()

    # ================================================================== #
    #  File operations
    # ================================================================== #

    @QtCore.Slot()
    def _on_open_panorama(self):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Panorama Image",
            "",
            "Images (*.png *.tif *.tiff *.bmp *.jpg *.jpeg);;All Files (*)",
        )
        if filepath:
            self._panorama_widget.load_image(filepath)

    @QtCore.Slot()
    def _on_save_calibration(self):
        if self._calibration.num_points == 0:
            QtWidgets.QMessageBox.information(
                self,
                "No Data",
                "No calibration points to save.",
            )
            return

        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Calibration",
            "calibration.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if filepath:
            try:
                self._calibration.save(filepath)
                self.statusBar().showMessage(f"Calibration saved to {filepath}", 5000)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Save Error", f"Failed to save:\n{e}"
                )

    @QtCore.Slot()
    def _on_load_calibration(self):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Calibration",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if filepath:
            try:
                self._calibration.load(filepath)
                self._refresh_calibration_ui()
                self.statusBar().showMessage(
                    f"Calibration loaded from {filepath}", 5000
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Load Error", f"Failed to load:\n{e}"
                )

    # ================================================================== #
    #  Hardware connections
    # ================================================================== #

    @QtCore.Slot()
    def _on_connect_xy(self):
        if self._xy is not None:
            QtWidgets.QMessageBox.information(
                self, "XY Table", "XY table is already connected."
            )
            return

        dlg = XYConnectDialog(self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._xy = dlg.create_xy_table()
            self._xy_control.set_xy_table(self._xy)
            self._update_hardware_status()
            logger.info("XY table connected.")
        except Exception as e:
            self._xy = None
            QtWidgets.QMessageBox.critical(
                self,
                "XY Connection Error",
                f"Failed to connect XY table:\n\n{e}",
            )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    @QtCore.Slot()
    def _on_disconnect_xy(self):
        if self._xy is None:
            return
        try:
            self._xy.close()
        except Exception as e:
            logger.warning(f"Error closing XY: {e}")
        self._xy = None
        self._xy_control.set_xy_table(None)
        self._update_hardware_status()

    @QtCore.Slot()
    def _on_connect_camera(self):
        if self._camera is not None and self._camera.is_open:
            QtWidgets.QMessageBox.information(
                self, "Camera", "Camera is already connected."
            )
            return

        try:
            self._camera = CameraAdapter()
            self._camera.open()
            self._camera.configure(exposure_us=1000.0)
            self._update_hardware_status()
            self._start_live_feed()

            QtWidgets.QMessageBox.information(
                self,
                "Camera Connected",
                f"Connected to: {self._camera.camera_name}\nLive preview started.",
            )
        except Exception as e:
            self._camera = None
            QtWidgets.QMessageBox.critical(
                self, "Camera Error", f"Failed to connect camera:\n{e}"
            )

    @QtCore.Slot()
    def _on_disconnect_camera(self):
        self._stop_live_feed()
        if self._camera is not None:
            self._camera.close()
            self._camera = None
            self._update_hardware_status()

    def _update_hardware_status(self):
        parts = []
        if self._xy is not None:
            parts.append("XY: Connected")
        else:
            parts.append("XY: N/A")

        if self._camera is not None and self._camera.is_open:
            cam_text = f"Camera: {self._camera.camera_name}"
            if self._live_worker and self._live_worker.is_streaming:
                cam_text += " [LIVE]"
            parts.append(cam_text)
        else:
            parts.append("Camera: N/A")

        self._hw_status_label.setText("  |  ".join(parts))

    # ================================================================== #
    #  Live camera feed
    # ================================================================== #

    def _start_live_feed(self):
        if self._camera is None or not self._camera.is_open:
            return
        if self._live_worker is not None and self._live_worker.is_streaming:
            return

        self._live_worker = LiveFeedWorker(self._camera)
        self._live_worker.frame_ready.connect(self._on_live_frame)
        self._live_worker.error_occurred.connect(self._on_live_error)
        self._live_worker.start()
        self._update_hardware_status()

    def _stop_live_feed(self):
        if self._live_worker is None:
            return
        self._live_worker.stop()
        self._live_worker.wait(3000)
        self._live_worker = None
        self._update_hardware_status()

    @QtCore.Slot(object)
    def _on_live_frame(self, frame: np.ndarray):
        self._preview_widget.update_live_frame(frame)

    @QtCore.Slot(str)
    def _on_live_error(self, msg: str):
        logger.error(f"Live feed error: {msg}")
        self._stop_live_feed()
        self.statusBar().showMessage(f"Camera error: {msg}", 5000)

    # ================================================================== #
    #  Window lifecycle
    # ================================================================== #

    def closeEvent(self, event: QtGui.QCloseEvent):
        # Stop move worker
        if self._move_worker is not None and self._move_worker.isRunning():
            self._move_worker.wait(3000)

        # Stop live feed
        self._stop_live_feed()

        # Close camera
        if self._camera is not None and self._camera.is_open:
            self._camera.close()

        # Close XY
        if self._xy is not None:
            try:
                self._xy.close()
            except Exception as e:
                logger.warning(f"Error closing XY on exit: {e}")

        event.accept()
