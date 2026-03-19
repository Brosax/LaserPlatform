"""
Scan configuration widget.

Provides a panel for configuring all scan parameters:
- Corner point marking (interactive via current XY position or manual input)
- Step sizes in X and Y directions
- Camera exposure time
- Settle time
- Output settings
- Grid info display (computed from config)
"""

import logging
import os
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..config import ScanConfig

logger = logging.getLogger(__name__)


class ScanConfigWidget(QtWidgets.QWidget):
    """
    Configuration panel for grid scan parameters.

    Signals
    -------
    config_changed(ScanConfig)
        Emitted when any configuration value changes.
    mark_corner_requested(int)
        Emitted when the user clicks "Mark Corner 1" or "Mark Corner 2".
        The int argument is the corner index (1 or 2).
    """

    config_changed = QtCore.Signal(object)  # ScanConfig
    mark_corner_requested = QtCore.Signal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._config = ScanConfig()
        self._setup_ui()
        self._update_grid_info()

    def _setup_ui(self):
        """Build the configuration panel layout."""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(6)

        # Title
        title = QtWidgets.QLabel("Scan Configuration")
        title_font = QtGui.QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title.setFont(title_font)
        main_layout.addWidget(title)

        # Scroll area for all settings
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(8)

        # --- Scan Area ---
        scan_group = self._create_group("Scan Area")
        scan_layout = QtWidgets.QFormLayout()

        # Corner 1 (Start)
        corner1_layout = QtWidgets.QHBoxLayout()
        self._corner1_x = QtWidgets.QDoubleSpinBox()
        self._corner1_x.setRange(-1e6, 1e6)
        self._corner1_x.setDecimals(1)
        self._corner1_x.setSuffix(" um")
        self._corner1_x.setValue(self._config.corner1[0])
        self._corner1_y = QtWidgets.QDoubleSpinBox()
        self._corner1_y.setRange(-1e6, 1e6)
        self._corner1_y.setDecimals(1)
        self._corner1_y.setSuffix(" um")
        self._corner1_y.setValue(self._config.corner1[1])
        self._mark_corner1_btn = QtWidgets.QPushButton("Mark")
        self._mark_corner1_btn.setToolTip("Set Start Point to current XY position")
        self._mark_corner1_btn.setMaximumWidth(50)
        corner1_layout.addWidget(self._corner1_x)
        corner1_layout.addWidget(self._corner1_y)
        corner1_layout.addWidget(self._mark_corner1_btn)
        scan_layout.addRow("Start Point:", corner1_layout)

        # Corner 2 (End)
        corner2_layout = QtWidgets.QHBoxLayout()
        self._corner2_x = QtWidgets.QDoubleSpinBox()
        self._corner2_x.setRange(-1e6, 1e6)
        self._corner2_x.setDecimals(1)
        self._corner2_x.setSuffix(" um")
        self._corner2_x.setValue(self._config.corner2[0])
        self._corner2_y = QtWidgets.QDoubleSpinBox()
        self._corner2_y.setRange(-1e6, 1e6)
        self._corner2_y.setDecimals(1)
        self._corner2_y.setSuffix(" um")
        self._corner2_y.setValue(self._config.corner2[1])
        self._mark_corner2_btn = QtWidgets.QPushButton("Mark")
        self._mark_corner2_btn.setToolTip("Set End Point to current XY position")
        self._mark_corner2_btn.setMaximumWidth(50)
        corner2_layout.addWidget(self._corner2_x)
        corner2_layout.addWidget(self._corner2_y)
        corner2_layout.addWidget(self._mark_corner2_btn)
        scan_layout.addRow("End Point:", corner2_layout)

        scan_group.setLayout(scan_layout)
        scroll_layout.addWidget(scan_group)

        # --- Step Size ---
        step_group = self._create_group("Step Size")
        step_layout = QtWidgets.QFormLayout()

        self._step_x = QtWidgets.QDoubleSpinBox()
        self._step_x.setRange(0.1, 1e6)
        self._step_x.setDecimals(1)
        self._step_x.setSuffix(" um")
        self._step_x.setValue(self._config.step_x_um)
        step_layout.addRow("X Step:", self._step_x)

        self._step_y = QtWidgets.QDoubleSpinBox()
        self._step_y.setRange(0.1, 1e6)
        self._step_y.setDecimals(1)
        self._step_y.setSuffix(" um")
        self._step_y.setValue(self._config.step_y_um)
        step_layout.addRow("Y Step:", self._step_y)

        step_group.setLayout(step_layout)
        scroll_layout.addWidget(step_group)

        # --- Camera ---
        cam_group = self._create_group("Camera")
        cam_layout = QtWidgets.QFormLayout()

        self._auto_exposure = QtWidgets.QCheckBox("Auto Exposure")
        self._auto_exposure.setChecked(self._config.auto_exposure)
        cam_layout.addRow("Mode:", self._auto_exposure)

        self._exposure = QtWidgets.QDoubleSpinBox()
        self._exposure.setRange(1.0, 1e7)
        self._exposure.setDecimals(1)
        self._exposure.setSuffix(" us")
        self._exposure.setValue(self._config.exposure_time_us)
        self._exposure.setEnabled(not self._config.auto_exposure)
        cam_layout.addRow("Exposure:", self._exposure)

        cam_group.setLayout(cam_layout)
        scroll_layout.addWidget(cam_group)

        # --- Motion ---
        motion_group = self._create_group("Motion")
        motion_layout = QtWidgets.QFormLayout()

        self._settle_time = QtWidgets.QDoubleSpinBox()
        self._settle_time.setRange(0.0, 10.0)
        self._settle_time.setDecimals(2)
        self._settle_time.setSuffix(" s")
        self._settle_time.setValue(self._config.settle_time_s)
        motion_layout.addRow("Settle Time:", self._settle_time)

        self._velocity = QtWidgets.QDoubleSpinBox()
        self._velocity.setRange(1.0, 1e6)
        self._velocity.setDecimals(0)
        self._velocity.setSuffix(" um/s")
        self._velocity.setValue(self._config.velocity_um_s)
        motion_layout.addRow("Velocity:", self._velocity)

        motion_group.setLayout(motion_layout)
        scroll_layout.addWidget(motion_group)

        # --- Output ---
        output_group = self._create_group("Output")
        output_layout = QtWidgets.QFormLayout()

        dir_layout = QtWidgets.QHBoxLayout()
        self._output_dir = QtWidgets.QLineEdit(self._config.output_directory)
        self._output_dir.setPlaceholderText("Default: ./scan_output")
        self._browse_btn = QtWidgets.QPushButton("...")
        self._browse_btn.setMaximumWidth(30)
        dir_layout.addWidget(self._output_dir)
        dir_layout.addWidget(self._browse_btn)
        output_layout.addRow("Directory:", dir_layout)

        output_group.setLayout(output_layout)
        scroll_layout.addWidget(output_group)

        # --- Grid Info (read-only) ---
        info_group = self._create_group("Grid Info")
        info_layout = QtWidgets.QFormLayout()

        self._info_grid_size = QtWidgets.QLabel("-")
        info_layout.addRow("Grid:", self._info_grid_size)

        self._info_total_tiles = QtWidgets.QLabel("-")
        info_layout.addRow("Total Positions:", self._info_total_tiles)

        self._info_scan_area = QtWidgets.QLabel("-")
        info_layout.addRow("Scan Area:", self._info_scan_area)

        self._info_time = QtWidgets.QLabel("-")
        info_layout.addRow("Est. Time:", self._info_time)

        info_group.setLayout(info_layout)
        scroll_layout.addWidget(info_group)

        # --- Validation ---
        self._validation_label = QtWidgets.QLabel("")
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet("color: #ff4444;")
        scroll_layout.addWidget(self._validation_label)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # --- Connect signals ---
        self._connect_signals()

    def _create_group(self, title: str) -> QtWidgets.QGroupBox:
        """Create a styled group box."""
        group = QtWidgets.QGroupBox(title)
        font = QtGui.QFont()
        font.setBold(True)
        group.setFont(font)
        return group

    def _connect_signals(self):
        """Connect all input widget signals to the update method."""
        # Corner marking
        self._mark_corner1_btn.clicked.connect(
            lambda: self.mark_corner_requested.emit(1)
        )
        self._mark_corner2_btn.clicked.connect(
            lambda: self.mark_corner_requested.emit(2)
        )

        # Value changes
        self._corner1_x.valueChanged.connect(self._on_value_changed)
        self._corner1_y.valueChanged.connect(self._on_value_changed)
        self._corner2_x.valueChanged.connect(self._on_value_changed)
        self._corner2_y.valueChanged.connect(self._on_value_changed)
        self._step_x.valueChanged.connect(self._on_value_changed)
        self._step_y.valueChanged.connect(self._on_value_changed)
        self._auto_exposure.toggled.connect(self._on_auto_exposure_toggled)
        self._exposure.valueChanged.connect(self._on_value_changed)
        self._settle_time.valueChanged.connect(self._on_value_changed)
        self._velocity.valueChanged.connect(self._on_value_changed)
        self._output_dir.textChanged.connect(self._on_value_changed)

        # Browse button
        self._browse_btn.clicked.connect(self._on_browse)

    def _on_auto_exposure_toggled(self, enabled: bool):
        """Toggle manual exposure input and update configuration."""
        self._exposure.setEnabled(not enabled)
        self._on_value_changed()

    def _on_value_changed(self, *_args):
        """Rebuild ScanConfig from widget values and emit."""
        self._config = ScanConfig(
            corner1=(self._corner1_x.value(), self._corner1_y.value()),
            corner2=(self._corner2_x.value(), self._corner2_y.value()),
            step_x_um=self._step_x.value(),
            step_y_um=self._step_y.value(),
            exposure_time_us=self._exposure.value(),
            auto_exposure=self._auto_exposure.isChecked(),
            settle_time_s=self._settle_time.value(),
            velocity_um_s=self._velocity.value(),
            output_directory=self._output_dir.text(),
        )

        self._update_grid_info()
        self._validate()
        self.config_changed.emit(self._config)

    def _on_browse(self):
        """Open directory picker for output directory."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self._output_dir.text() or os.getcwd(),
        )
        if directory:
            self._output_dir.setText(directory)

    def _update_grid_info(self):
        """Update the computed grid info labels."""
        cfg = self._config
        self._info_grid_size.setText(f"{cfg.num_rows} x {cfg.num_cols}")
        self._info_total_tiles.setText(str(cfg.total_tiles))
        self._info_scan_area.setText(
            f"{cfg.scan_range_x:.0f} x {cfg.scan_range_y:.0f} um"
        )

        # Estimate scan time
        from ..scanner.grid_scanner import GridScanner

        scanner = GridScanner(cfg)
        est_time = scanner.estimate_scan_time_s()
        if est_time < 60:
            self._info_time.setText(f"{est_time:.0f} s")
        elif est_time < 3600:
            self._info_time.setText(f"{est_time / 60:.1f} min")
        else:
            self._info_time.setText(f"{est_time / 3600:.1f} h")

    def _validate(self):
        """Run validation and display errors."""
        errors = self._config.validate()
        if errors:
            self._validation_label.setText("\n".join(errors))
        else:
            self._validation_label.setText("")

    def set_corner(self, corner_index: int, x_um: float, y_um: float):
        """
        Set a corner position (called from main window after reading XY position).

        Parameters
        ----------
        corner_index : int
            1 or 2.
        x_um : float
            X position in um.
        y_um : float
            Y position in um.
        """
        if corner_index == 1:
            self._corner1_x.setValue(x_um)
            self._corner1_y.setValue(y_um)
        elif corner_index == 2:
            self._corner2_x.setValue(x_um)
            self._corner2_y.setValue(y_um)

    def get_config(self) -> ScanConfig:
        """Return the current ScanConfig."""
        return self._config

    def set_enabled(self, enabled: bool):
        """Enable or disable all input widgets (e.g., during scan)."""
        widget_types = [
            QtWidgets.QDoubleSpinBox,
            QtWidgets.QSpinBox,
            QtWidgets.QSlider,
            QtWidgets.QComboBox,
            QtWidgets.QCheckBox,
            QtWidgets.QPushButton,
            QtWidgets.QLineEdit,
        ]
        for widget_type in widget_types:
            for widget in self.findChildren(widget_type):
                widget.setEnabled(enabled)
