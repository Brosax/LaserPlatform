"""
Main window for the Image Stitcher application.

Assembles all sub-widgets (config panel, preview, progress, XY control)
and manages hardware connections (XY table via standalone SMC100 driver,
camera), live camera feed, and scan lifecycle.

No dependency on ``analyzr2`` or the ``xyz_table`` package.
"""

import logging
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..config import ScanConfig
from ..acquisition.camera_adapter import CameraAdapter, LiveFeedWorker
from ..acquisition.smc100_axis import SMC100Axis
from ..acquisition.xy_table import XYTable
from ..scanner.scan_coordinator import ScanCoordinator, ScanWorker
from .preview_widget import PreviewWidget
from .scan_config_widget import ScanConfigWidget
from .progress_widget import ProgressWidget
from .xy_control_widget import XYControlWidget

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  XY Connection Dialog
# ------------------------------------------------------------------ #


class XYConnectDialog(QtWidgets.QDialog):
    """
    Dialog for configuring and connecting the XY table.

    X and Y axes share the same COM port (daisy-chained SMC100
    controllers), only the address differs.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect XY Table")
        self.setMinimumWidth(380)

        layout = QtWidgets.QVBoxLayout(self)

        # ---- XY shared settings ----
        xy_group = QtWidgets.QGroupBox("XY Axes (shared COM port)")
        xy_form = QtWidgets.QFormLayout(xy_group)

        # COM port
        port_row = QtWidgets.QHBoxLayout()
        self._xy_port = QtWidgets.QComboBox()
        self._xy_port.setEditable(True)
        port_row.addWidget(self._xy_port, stretch=1)
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.setMaximumWidth(60)
        refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(refresh_btn)
        xy_form.addRow("COM Port:", port_row)

        # X address
        self._x_address = QtWidgets.QSpinBox()
        self._x_address.setRange(0, 31)
        self._x_address.setValue(1)
        xy_form.addRow("X Address:", self._x_address)

        # Y address
        self._y_address = QtWidgets.QSpinBox()
        self._y_address.setRange(0, 31)
        self._y_address.setValue(2)
        xy_form.addRow("Y Address:", self._y_address)

        # Timeout
        self._xy_timeout = QtWidgets.QDoubleSpinBox()
        self._xy_timeout.setRange(0.1, 60.0)
        self._xy_timeout.setValue(1.0)
        self._xy_timeout.setSuffix(" s")
        self._xy_timeout.setDecimals(1)
        xy_form.addRow("Timeout:", self._xy_timeout)

        layout.addWidget(xy_group)

        # ---- Homing ----
        self._homing_check = QtWidgets.QCheckBox("Run homing after connect")
        self._homing_check.setChecked(False)
        layout.addWidget(self._homing_check)

        # ---- Buttons ----
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        self._connect_btn = QtWidgets.QPushButton("Connect")
        self._connect_btn.setDefault(True)
        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        btn_layout.addWidget(self._connect_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

        self._connect_btn.clicked.connect(self.accept)
        self._cancel_btn.clicked.connect(self.reject)

        # Populate COM ports and apply defaults
        self._refresh_ports()
        self._apply_defaults()

    def _refresh_ports(self):
        """Scan available serial ports and populate the combo box."""
        current = self._xy_port.currentText()
        self._xy_port.clear()
        try:
            import serial.tools.list_ports

            for info in serial.tools.list_ports.comports():
                self._xy_port.addItem(
                    f"{info.device} - {info.description}", info.device
                )
        except ImportError:
            logger.warning("pyserial not installed, cannot list COM ports.")
        idx = self._xy_port.findText(current)
        if idx >= 0:
            self._xy_port.setCurrentIndex(idx)

    def _apply_defaults(self):
        """Pre-fill defaults: COM11, X=1, Y=2."""
        idx = self._xy_port.findData("COM11")
        if idx >= 0:
            self._xy_port.setCurrentIndex(idx)
        else:
            self._xy_port.setEditText("COM11")

    def _get_com_port(self) -> str:
        """Extract the raw COM port string from the combo box."""
        data = self._xy_port.currentData()
        return data if data else self._xy_port.currentText().split(" - ")[0].strip()

    def create_xy_table(self) -> XYTable:
        """
        Instantiate SMC100Axis objects and build an ``XYTable``.

        Returns
        -------
        XYTable
            The connected XY table object.
        """
        port = self._get_com_port()
        timeout = self._xy_timeout.value()

        x_axis = SMC100Axis(port, self._x_address.value(), timeout)
        y_axis = SMC100Axis(port, self._y_address.value(), timeout)

        xy = XYTable(x_axis, y_axis)

        if self._homing_check.isChecked():
            xy.homing()

        return xy


# ------------------------------------------------------------------ #
#  Main Window
# ------------------------------------------------------------------ #


class MainWindow(QtWidgets.QMainWindow):
    """
    Main application window for the Image Stitcher.

    Layout:
    +-----------------------------------------+
    |  Menu Bar                               |
    +------------+----------------------------+
    |            |                            |
    | Config     |     Preview                |
    | + XY Ctrl  |     (real-time composite)  |
    | (left)     |                            |
    |            |                            |
    +------------+----------------------------+
    |  Progress Bar + Controls (bottom)       |
    +-----------------------------------------+
    """

    def __init__(
        self,
        xy_table: Optional[XYTable] = None,
        camera: Optional[CameraAdapter] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)

        self._xy: Optional[XYTable] = xy_table
        self._camera = camera
        self._coordinator: Optional[ScanCoordinator] = None
        self._scan_worker: Optional[ScanWorker] = None
        self._live_worker: Optional[LiveFeedWorker] = None

        self._setup_ui()
        self._setup_menu()
        self._connect_signals()

        self.setWindowTitle("Image Stitcher")
        self.resize(1200, 800)

        # Sync hardware state with widgets
        self._update_hardware_status()
        if self._xy is not None:
            self._xy_control.set_xy_table(self._xy)

    def _setup_ui(self):
        """Create the main layout with config, XY control, preview, and progress."""
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # --- Top area: left panel + preview (right) ---
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # Left panel: config + XY control stacked
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._config_widget = ScanConfigWidget()
        left_layout.addWidget(self._config_widget, stretch=1)

        self._xy_control = XYControlWidget()
        left_layout.addWidget(self._xy_control, stretch=0)

        left_panel.setMinimumWidth(280)
        left_panel.setMaximumWidth(420)
        splitter.addWidget(left_panel)

        # Preview (right)
        self._preview_widget = PreviewWidget()
        splitter.addWidget(self._preview_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter, stretch=1)

        # --- Bottom: progress + controls ---
        self._progress_widget = ProgressWidget()
        main_layout.addWidget(self._progress_widget)

        # --- Status bar ---
        self._hw_status_label = QtWidgets.QLabel("Hardware: Not connected")
        self.statusBar().addPermanentWidget(self._hw_status_label)

    def _setup_menu(self):
        """Create the menu bar."""
        menubar = self.menuBar()

        # --- Hardware menu ---
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

        hw_menu.addSeparator()

        self._detect_image_size_action = hw_menu.addAction("Detect Image Size")
        self._detect_image_size_action.triggered.connect(self._on_detect_image_size)

        # --- View menu ---
        view_menu = menubar.addMenu("View")

        self._fit_preview_action = view_menu.addAction("Fit Preview")
        self._fit_preview_action.setShortcut("Ctrl+F")
        self._fit_preview_action.triggered.connect(
            lambda: self._preview_widget._fit_to_view()
        )

        self._clear_preview_action = view_menu.addAction("Clear Preview")
        self._clear_preview_action.triggered.connect(self._preview_widget.clear)

    def _connect_signals(self):
        """Connect widget signals to slots."""
        # Config changes -> update preview grid overlay
        self._config_widget.config_changed.connect(self._on_config_changed)

        # Corner marking -> read XY position
        self._config_widget.mark_corner_requested.connect(self._on_mark_corner)

        # Progress control buttons
        self._progress_widget.start_requested.connect(self._on_start_scan)
        self._progress_widget.pause_requested.connect(self._on_pause_scan)
        self._progress_widget.resume_requested.connect(self._on_resume_scan)
        self._progress_widget.abort_requested.connect(self._on_abort_scan)

    # ------------------------------------------------------------------ #
    #  Config slots
    # ------------------------------------------------------------------ #

    def _on_config_changed(self, config: ScanConfig):
        """Handle configuration changes."""
        self._preview_widget.set_grid_info(config.num_rows, config.num_cols)

    def _on_mark_corner(self, corner_index: int):
        """Read the current XY position and set it as a corner."""
        if self._xy is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No XY Table",
                "XY table is not connected. Cannot read position.",
            )
            return

        try:
            x_um, y_um = self._xy.update_position()
            self._config_widget.set_corner(corner_index, x_um, y_um)
            logger.info(f"Corner {corner_index} marked at ({x_um:.1f}, {y_um:.1f}) um")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Position Read Error",
                f"Failed to read XY position: {e}",
            )

    # ------------------------------------------------------------------ #
    #  Hardware slots
    # ------------------------------------------------------------------ #

    def _on_connect_xy(self):
        """Open the XY connection dialog."""
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
            logger.info("XY table connected successfully.")
        except Exception as e:
            self._xy = None
            QtWidgets.QMessageBox.critical(
                self,
                "XY Connection Error",
                f"Failed to connect XY table:\n\n{e}",
            )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _on_disconnect_xy(self):
        """Close the XY table connection."""
        if self._xy is None:
            return
        try:
            self._xy.close()
        except Exception as e:
            logger.warning(f"Error while closing XY table: {e}")

        self._xy = None
        self._xy_control.set_xy_table(None)
        self._update_hardware_status()
        logger.info("XY table disconnected.")

    def _on_connect_camera(self):
        """Open the camera connection and start live preview."""
        if self._camera is not None and self._camera.is_open:
            QtWidgets.QMessageBox.information(
                self, "Camera", "Camera is already connected."
            )
            return

        try:
            self._camera = CameraAdapter()
            self._camera.open()

            config = self._config_widget.get_config()
            self._camera.configure(exposure_us=config.exposure_time_us)

            # Auto-detect image size and fill config
            try:
                h, w = self._camera.get_image_shape()
                self._config_widget._img_width.setValue(w)
                self._config_widget._img_height.setValue(h)
            except Exception:
                pass

            self._update_hardware_status()

            # Auto-start live preview
            self._start_live_feed()

            QtWidgets.QMessageBox.information(
                self,
                "Camera Connected",
                f"Connected to: {self._camera.camera_name}\nLive preview started.",
            )
        except Exception as e:
            self._camera = None
            QtWidgets.QMessageBox.critical(
                self, "Camera Error", f"Failed to connect camera: {e}"
            )

    def _on_disconnect_camera(self):
        """Stop live feed, then close the camera connection."""
        self._stop_live_feed()

        if self._camera is not None:
            self._camera.close()
            self._camera = None
            self._update_hardware_status()

    def _on_detect_image_size(self):
        """Read image dimensions from the camera and update config."""
        if self._camera is None or not self._camera.is_open:
            QtWidgets.QMessageBox.warning(self, "Camera", "Camera is not connected.")
            return

        try:
            h, w = self._camera.get_image_shape()
            self._config_widget._img_width.setValue(w)
            self._config_widget._img_height.setValue(h)
            QtWidgets.QMessageBox.information(
                self,
                "Image Size Detected",
                f"Camera image size: {w} x {h} pixels",
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to detect image size: {e}"
            )

    def _update_hardware_status(self):
        """Update the status bar with hardware connection info."""
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
            parts.append("Camera: Not connected")

        self._hw_status_label.setText("  |  ".join(parts))

    # ------------------------------------------------------------------ #
    #  Live camera feed
    # ------------------------------------------------------------------ #

    def _start_live_feed(self):
        """Start the live camera feed worker thread."""
        if self._camera is None or not self._camera.is_open:
            return
        if self._live_worker is not None and self._live_worker.is_streaming:
            return

        self._live_worker = LiveFeedWorker(self._camera)
        self._live_worker.frame_ready.connect(self._on_live_frame)
        self._live_worker.error_occurred.connect(self._on_live_error)
        self._live_worker.finished.connect(self._on_live_finished)

        self._preview_widget.set_mode("live")

        self._live_worker.start()
        self._update_hardware_status()
        logger.info("Live feed started.")

    def _stop_live_feed(self):
        """Stop the live camera feed and wait for the thread to finish."""
        if self._live_worker is None:
            return

        self._live_worker.stop()
        self._live_worker.wait(3000)
        self._live_worker = None
        self._update_hardware_status()
        logger.info("Live feed stopped.")

    @QtCore.Slot(object)
    def _on_live_frame(self, frame: np.ndarray):
        self._preview_widget.update_live_frame(frame)

    @QtCore.Slot(str)
    def _on_live_error(self, error_msg: str):
        logger.error(f"Live feed error: {error_msg}")
        self._stop_live_feed()
        self.statusBar().showMessage(f"Live feed error: {error_msg}", 5000)

    def _on_live_finished(self):
        self._update_hardware_status()
        logger.info("Live feed worker finished.")

    # ------------------------------------------------------------------ #
    #  Scan control slots
    # ------------------------------------------------------------------ #

    def _on_start_scan(self):
        """Start a new scan."""
        config = self._config_widget.get_config()

        errors = config.validate()
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Configuration",
                "Please fix the following errors:\n\n" + "\n".join(errors),
            )
            return

        if self._xy is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No XY Table",
                "XY table is not connected.\n\n"
                "Use Hardware > Connect XY Table... to connect.",
            )
            return

        if self._camera is None or not self._camera.is_open:
            QtWidgets.QMessageBox.warning(
                self,
                "No Camera",
                "Camera is not connected. Use Hardware > Connect Camera.",
            )
            return

        # Stop live feed — camera cannot stream and capture simultaneously
        self._stop_live_feed()

        # Configure camera exposure
        self._camera.configure(exposure_us=config.exposure_time_us)

        # Set up coordinator
        self._coordinator = ScanCoordinator()
        self._coordinator.configure(config, self._xy, self._camera)

        # Connect coordinator signals
        self._coordinator.progress_updated.connect(self._on_progress_updated)
        self._coordinator.preview_ready.connect(self._on_preview_ready)
        self._coordinator.tile_captured.connect(self._on_tile_captured)
        self._coordinator.scan_finished.connect(self._on_scan_finished)
        self._coordinator.scan_error.connect(self._on_scan_error)
        self._coordinator.scan_aborted.connect(self._on_scan_aborted)
        self._coordinator.position_updated.connect(self._on_position_updated)
        self._coordinator.eta_updated.connect(self._on_eta_updated)

        # Set up worker thread
        self._scan_worker = ScanWorker(self._coordinator)
        self._scan_worker.finished.connect(self._on_worker_finished)

        # Update UI state
        self._config_widget.set_enabled(False)
        self._xy_control.setEnabled(False)
        self._progress_widget.reset()
        self._progress_widget.set_state("running")
        self._preview_widget.set_mode("composite")
        self._preview_widget.clear()
        self._preview_widget.set_grid_info(config.num_rows, config.num_cols)

        logger.info("Starting scan worker thread...")
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

    @QtCore.Slot(object)
    def _on_preview_ready(self, preview: np.ndarray):
        self._preview_widget.update_preview(preview)

    @QtCore.Slot(int, int, int)
    def _on_tile_captured(self, row: int, col: int, idx: int):
        self._preview_widget.set_current_tile(row, col)

    @QtCore.Slot(str)
    def _on_scan_finished(self, output_path: str):
        self._progress_widget.set_state("finished")
        self._config_widget.set_enabled(True)
        self._xy_control.setEnabled(True)
        self._start_live_feed()
        QtWidgets.QMessageBox.information(
            self,
            "Scan Complete",
            f"Scan completed successfully.\n\nOutput saved to:\n{output_path}",
        )

    @QtCore.Slot(str)
    def _on_scan_error(self, error_msg: str):
        self._progress_widget.set_state("error")
        self._config_widget.set_enabled(True)
        self._xy_control.setEnabled(True)
        self._start_live_feed()
        QtWidgets.QMessageBox.critical(
            self,
            "Scan Error",
            f"An error occurred during scanning:\n\n{error_msg}",
        )

    @QtCore.Slot()
    def _on_scan_aborted(self):
        self._progress_widget.set_state("aborted")
        self._config_widget.set_enabled(True)
        self._xy_control.setEnabled(True)
        self._start_live_feed()
        QtWidgets.QMessageBox.information(
            self, "Scan Aborted", "The scan was aborted by the user."
        )

    @QtCore.Slot(float, float, float)
    def _on_position_updated(self, x_um: float, y_um: float, z_um: float):
        self._progress_widget.update_position(x_um, y_um, z_um)

    @QtCore.Slot(float)
    def _on_eta_updated(self, eta_s: float):
        self._progress_widget.update_eta(eta_s)

    def _on_worker_finished(self):
        self._scan_worker = None
        logger.info("Scan worker thread finished.")

    # ------------------------------------------------------------------ #
    #  Window lifecycle
    # ------------------------------------------------------------------ #

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Handle window close: abort scan, stop live feed, clean up hardware."""
        # Abort running scan
        if self._coordinator and self._coordinator.is_running:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Scan in Progress",
                "A scan is currently running. Abort and close?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.No:
                event.ignore()
                return

            self._coordinator.abort()
            if self._scan_worker is not None:
                self._scan_worker.wait(5000)

        # Stop live feed
        self._stop_live_feed()

        # Close camera
        if self._camera is not None and self._camera.is_open:
            self._camera.close()

        # Close XY table
        if self._xy is not None:
            try:
                self._xy.close()
            except Exception as e:
                logger.warning(f"Error closing XY table on exit: {e}")

        event.accept()
