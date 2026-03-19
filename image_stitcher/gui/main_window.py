"""
Main window for the S-pattern scan application.

Assembles all sub-widgets (config panel, preview, progress, XY control)
and manages hardware connections (XY table via standalone SMC100 driver,
camera), live camera feed, and scan lifecycle with user confirmation
at each grid position.

No dependency on ``analyzr2`` or the ``xyz_table`` package.
"""

import logging
import os
from datetime import datetime
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..config import ScanConfig
from ..acquisition.camera_adapter import CameraAdapter, LiveFeedWorker
from ..acquisition.mlj250_axis import MLJ250Axis
from ..acquisition.smc100_axis import SMC100Axis
from ..acquisition.xy_table import XYTable
from ..scanner.scan_coordinator import ScanCoordinator, ScanWorker
from ..utils.image_io import save_png_8bit
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
    Dialog for configuring and connecting the XY(Z) table.

    X and Y axes share the same COM port (daisy-chained SMC100
    controllers), only the address differs.  The Z axis is optional
    and uses its own separate COM port.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect XY(Z) Table")
        self.setMinimumWidth(400)

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

        # ---- Z axis (optional, separate COM port) ----
        self._z_enable = QtWidgets.QCheckBox("Enable Z axis")
        self._z_enable.setChecked(False)
        layout.addWidget(self._z_enable)

        self._z_group = QtWidgets.QGroupBox("Z Axis (separate COM port)")
        z_form = QtWidgets.QFormLayout(self._z_group)

        z_port_row = QtWidgets.QHBoxLayout()
        self._z_port = QtWidgets.QComboBox()
        self._z_port.setEditable(True)
        z_port_row.addWidget(self._z_port, stretch=1)
        z_refresh_btn = QtWidgets.QPushButton("Refresh")
        z_refresh_btn.setMaximumWidth(60)
        z_refresh_btn.clicked.connect(self._refresh_ports)
        z_port_row.addWidget(z_refresh_btn)
        z_form.addRow("COM Port:", z_port_row)

        self._z_type = QtWidgets.QComboBox()
        self._z_type.addItems(["Thorlabs MLJ250", "SMC100"])
        z_form.addRow("Controller:", self._z_type)

        self._z_address = QtWidgets.QSpinBox()
        self._z_address.setRange(0, 31)
        self._z_address.setValue(1)
        z_form.addRow("Z Address:", self._z_address)

        self._z_timeout = QtWidgets.QDoubleSpinBox()
        self._z_timeout.setRange(0.1, 60.0)
        self._z_timeout.setValue(3.0)
        self._z_timeout.setSuffix(" s")
        self._z_timeout.setDecimals(1)
        z_form.addRow("Timeout:", self._z_timeout)

        layout.addWidget(self._z_group)

        # Toggle Z group enabled state from checkbox
        self._z_group.setEnabled(False)
        self._z_enable.toggled.connect(self._z_group.setEnabled)
        self._z_type.currentTextChanged.connect(self._on_z_type_changed)

        # ---- Homing ----
        self._homing_check = QtWidgets.QCheckBox("Run homing after connect (XY only)")
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
        self._on_z_type_changed(self._z_type.currentText())

    def _refresh_ports(self):
        """Scan available serial ports and populate both combo boxes."""
        for combo in (self._xy_port, self._z_port):
            current = combo.currentText()
            combo.clear()
            try:
                import serial.tools.list_ports

                for info in serial.tools.list_ports.comports():
                    combo.addItem(f"{info.device} - {info.description}", info.device)
            except ImportError:
                logger.warning("pyserial not installed, cannot list COM ports.")
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _apply_defaults(self):
        """Pre-fill defaults: XY on COM11, Z on COM12."""
        idx = self._xy_port.findData("COM11")
        if idx >= 0:
            self._xy_port.setCurrentIndex(idx)
        else:
            self._xy_port.setEditText("COM11")

        idx_z = self._z_port.findData("COM12")
        if idx_z >= 0:
            self._z_port.setCurrentIndex(idx_z)
        else:
            self._z_port.setEditText("COM12")

    def _get_com_port(self, combo: QtWidgets.QComboBox) -> str:
        """Extract the raw COM port string from a combo box."""
        data = combo.currentData()
        return data if data else combo.currentText().split(" - ")[0].strip()

    def _on_z_type_changed(self, z_type: str):
        """Adjust Z options depending on selected controller type."""
        is_smc100 = z_type == "SMC100"
        self._z_address.setEnabled(is_smc100)

    def create_xy_table(self) -> XYTable:
        """
        Instantiate SMC100Axis objects and build an ``XYTable``.

        If the Z axis checkbox is enabled, a third axis is created on
        the separate Z COM port and passed to XYTable.

        Returns
        -------
        XYTable
            The connected XY(Z) table object.
        """

        def _safe_close(axis_obj):
            if axis_obj is None:
                return
            try:
                axis_obj.close()
            except Exception as close_err:
                logger.warning("Axis close failed during cleanup: %s", close_err)

        xy_port = self._get_com_port(self._xy_port)
        xy_timeout = self._xy_timeout.value()

        x_axis = None
        y_axis = None
        z_axis = None

        try:
            x_axis = SMC100Axis(xy_port, self._x_address.value(), xy_timeout)
            y_axis = SMC100Axis(xy_port, self._y_address.value(), xy_timeout)

            if self._z_enable.isChecked():
                z_port = self._get_com_port(self._z_port)
                z_timeout = self._z_timeout.value()
                try:
                    if self._z_type.currentText() == "SMC100":
                        z_axis = SMC100Axis(z_port, self._z_address.value(), z_timeout)
                    else:
                        z_axis = MLJ250Axis(z_port, z_timeout)
                except Exception as z_err:
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "Z Axis Connection Failed",
                        "Z axis failed to connect:\n\n"
                        f"{z_err}\n\n"
                        "Continue with XY only?",
                        QtWidgets.QMessageBox.StandardButton.Yes
                        | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes,
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        logger.warning(
                            "Z connection failed; continuing with XY only: %s", z_err
                        )
                        z_axis = None
                    else:
                        raise

            xy = XYTable(x_axis, y_axis, z_axis)
        except Exception:
            _safe_close(z_axis)
            _safe_close(y_axis)
            _safe_close(x_axis)
            raise

        if self._homing_check.isChecked():
            xy.homing()

        return xy


# ------------------------------------------------------------------ #
#  Main Window
# ------------------------------------------------------------------ #


class MainWindow(QtWidgets.QMainWindow):
    """
    Main application window for S-pattern scan with user confirmation.

    Layout:
    +-----------------------------------------+
    |  Menu Bar                               |
    +------------+----------------------------+
    |            |                            |
    | Config     |     Preview                |
    | + XY Ctrl  |     (live camera feed)     |
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

        self.setWindowTitle("S-Pattern Scanner")
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

        # --- Capture menu ---
        capture_menu = menubar.addMenu("Capture")

        self._save_screenshot_action = capture_menu.addAction("Save Screenshot")
        self._save_screenshot_action.setShortcut("Ctrl+S")
        self._save_screenshot_action.triggered.connect(self._on_save_screenshot)

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
        # Config changes
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
        """Handle configuration changes (no-op now that grid overlay is removed)."""
        pass

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

    def _update_hardware_status(self):
        """Update the status bar with hardware connection info."""
        parts = []

        if self._xy is not None:
            xy_text = "XY: Connected"
            if self._xy.has_z:
                xy_text += " + Z"
            parts.append(xy_text)
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
    #  Save screenshot
    # ------------------------------------------------------------------ #

    def _on_save_screenshot(self):
        """
        Capture a single frame from the camera and save it as PNG.

        If the live feed is running, it is stopped briefly so the camera
        can capture, then restarted.
        """
        if self._camera is None or not self._camera.is_open:
            QtWidgets.QMessageBox.warning(
                self,
                "No Camera",
                "Camera is not connected. Use Hardware > Connect Camera.",
            )
            return

        # Determine output directory: use config value, or ask the user
        config = self._config_widget.get_config()
        output_dir = config.output_directory
        if not output_dir:
            output_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select Screenshot Output Directory"
            )
            if not output_dir:
                return  # cancelled

        os.makedirs(output_dir, exist_ok=True)

        # Build timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath_base = os.path.join(output_dir, f"screenshot_{timestamp}")

        # Stop live feed so camera is free for single capture
        was_live = self._live_worker is not None and self._live_worker.is_streaming
        if was_live:
            self._stop_live_feed()

        try:
            image = self._camera.capture_single()
            ok = save_png_8bit(image, filepath_base)
            png_path = f"{filepath_base}.png"

            if ok:
                self.statusBar().showMessage(f"Screenshot saved: {png_path}", 5000)
                logger.info(f"Screenshot saved: {png_path}")
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Screenshot Error",
                    f"Failed to save PNG screenshot:\n\n{png_path}",
                )

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Screenshot Error",
                f"Failed to capture screenshot:\n\n{e}",
            )
            logger.error(f"Screenshot capture failed: {e}")

        finally:
            # Restart live feed if it was running before
            if was_live:
                self._start_live_feed()

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

        # Configure camera exposure mode
        self._camera.configure(exposure_us=config.exposure_time_us)

        # Set up coordinator
        self._coordinator = ScanCoordinator()
        self._coordinator.configure(config, self._xy, self._camera)

        # Connect coordinator signals
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

        # Set up worker thread
        self._scan_worker = ScanWorker(self._coordinator)
        self._scan_worker.finished.connect(self._on_worker_finished)

        # Update UI state
        self._config_widget.set_enabled(False)
        self._xy_control.setEnabled(False)
        self._progress_widget.reset()
        self._progress_widget.set_state("running")
        self._preview_widget.clear()

        # NOTE: Do NOT start live feed here. The live feed and
        # capture_single() both call cam.get_frame() and cannot run
        # concurrently. Instead, the live feed is started/stopped
        # around each confirmation dialog in _on_confirm_capture_requested.

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

    @QtCore.Slot(int, int, int)
    def _on_tile_captured(self, row: int, col: int, idx: int):
        logger.info(f"Tile captured: row={row}, col={col}, idx={idx}")

    @QtCore.Slot(int, int, float, float)
    def _on_confirm_capture_requested(
        self, row: int, col: int, x_um: float, y_um: float
    ):
        """
        Handle user confirmation request from the scan coordinator.

        Starts the live camera feed so the user can observe the current
        view, shows position info overlay, and pops up a dialog asking
        if the image is clear. The live feed is stopped before returning
        so the coordinator can safely call capture_single().

        Parameters
        ----------
        row : int
            1-indexed row number.
        col : int
            1-indexed column number.
        x_um : float
            Current X position in um.
        y_um : float
            Current Y position in um.
        """
        # Update position overlay on preview
        pos_text = f"Position ({row},{col}) - X={x_um:.1f}, Y={y_um:.1f} um"
        self._preview_widget.set_position_text(pos_text)

        # Start live feed so user can see the camera view
        self._start_live_feed()

        # Show confirmation dialog
        msgbox = QtWidgets.QMessageBox(self)
        msgbox.setWindowTitle("Confirm Capture")
        msgbox.setText(
            f"Position ({row}, {col})\n"
            f"X = {x_um:.1f} um,  Y = {y_um:.1f} um\n\n"
            "Is the image clear?"
        )
        msgbox.setIcon(QtWidgets.QMessageBox.Icon.Question)

        capture_btn = msgbox.addButton(
            "Capture", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        skip_btn = msgbox.addButton("Skip", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msgbox.setDefaultButton(capture_btn)

        msgbox.exec()

        # Stop live feed BEFORE responding — camera must be free for
        # capture_single() in the coordinator thread
        self._stop_live_feed()

        clicked = msgbox.clickedButton()
        if clicked == capture_btn:
            self._coordinator.confirm_capture()
        else:
            self._coordinator.skip_capture()

        # Clear position overlay after response
        self._preview_widget.set_position_text("")

    @QtCore.Slot(str)
    def _on_scan_finished(self, output_path: str):
        self._stop_live_feed()
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
        self._stop_live_feed()
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
        self._stop_live_feed()
        self._progress_widget.set_state("aborted")
        self._config_widget.set_enabled(True)
        self._xy_control.setEnabled(True)
        self._start_live_feed()
        QtWidgets.QMessageBox.information(
            self, "Scan Aborted", "The scan was aborted by the user."
        )

    @QtCore.Slot(float, float)
    def _on_position_updated(self, x_um: float, y_um: float):
        self._progress_widget.update_position(x_um, y_um)

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
