"""
Scan configuration widget.

Provides a panel for configuring all scan parameters:
- Corner point marking (interactive via current XYZ position)
- Overlap ratio slider
- Camera exposure time
- Settle time
- Feature matching method
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

        # Corner 1
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
        self._mark_corner1_btn.setToolTip("Set Corner 1 to current XYZ position")
        self._mark_corner1_btn.setMaximumWidth(50)
        corner1_layout.addWidget(self._corner1_x)
        corner1_layout.addWidget(self._corner1_y)
        corner1_layout.addWidget(self._mark_corner1_btn)
        scan_layout.addRow("Corner 1:", corner1_layout)

        # Corner 2
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
        self._mark_corner2_btn.setToolTip("Set Corner 2 to current XYZ position")
        self._mark_corner2_btn.setMaximumWidth(50)
        corner2_layout.addWidget(self._corner2_x)
        corner2_layout.addWidget(self._corner2_y)
        corner2_layout.addWidget(self._mark_corner2_btn)
        scan_layout.addRow("Corner 2:", corner2_layout)

        # Z position (optional — disabled when Z axis is not connected)
        self._z_position_label = QtWidgets.QLabel("Z Position:")
        self._z_position = QtWidgets.QDoubleSpinBox()
        self._z_position.setRange(-1e6, 1e6)
        self._z_position.setDecimals(1)
        self._z_position.setSuffix(" um")
        self._z_position.setValue(self._config.z_position)
        self._z_position.setEnabled(False)
        self._z_position.setToolTip("Connect a Z axis to enable this field")
        scan_layout.addRow(self._z_position_label, self._z_position)

        scan_group.setLayout(scan_layout)
        scroll_layout.addWidget(scan_group)

        # --- Overlap ---
        overlap_group = self._create_group("Overlap")
        overlap_layout = QtWidgets.QFormLayout()

        overlap_h = QtWidgets.QHBoxLayout()
        self._overlap_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._overlap_slider.setRange(5, 50)
        self._overlap_slider.setValue(int(self._config.overlap_ratio * 100))
        self._overlap_label = QtWidgets.QLabel(
            f"{self._config.overlap_ratio * 100:.0f}%"
        )
        self._overlap_label.setMinimumWidth(35)
        overlap_h.addWidget(self._overlap_slider)
        overlap_h.addWidget(self._overlap_label)
        overlap_layout.addRow("Overlap:", overlap_h)

        overlap_group.setLayout(overlap_layout)
        scroll_layout.addWidget(overlap_group)

        # --- Camera ---
        cam_group = self._create_group("Camera")
        cam_layout = QtWidgets.QFormLayout()

        self._exposure = QtWidgets.QDoubleSpinBox()
        self._exposure.setRange(1.0, 1e7)
        self._exposure.setDecimals(1)
        self._exposure.setSuffix(" us")
        self._exposure.setValue(self._config.exposure_time_us)
        cam_layout.addRow("Exposure:", self._exposure)

        self._pixel_size = QtWidgets.QDoubleSpinBox()
        self._pixel_size.setRange(0.01, 1000.0)
        self._pixel_size.setDecimals(2)
        self._pixel_size.setSuffix(" um/px")
        self._pixel_size.setValue(self._config.pixel_size_um)
        cam_layout.addRow("Pixel Size:", self._pixel_size)

        img_size_layout = QtWidgets.QHBoxLayout()
        self._img_width = QtWidgets.QSpinBox()
        self._img_width.setRange(1, 65536)
        self._img_width.setValue(self._config.image_width)
        self._img_width.setSuffix(" px")
        self._img_height = QtWidgets.QSpinBox()
        self._img_height.setRange(1, 65536)
        self._img_height.setValue(self._config.image_height)
        self._img_height.setSuffix(" px")
        img_size_layout.addWidget(self._img_width)
        img_size_layout.addWidget(QtWidgets.QLabel("x"))
        img_size_layout.addWidget(self._img_height)
        cam_layout.addRow("Image Size:", img_size_layout)

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

        # --- Stitching ---
        stitch_group = self._create_group("Stitching")
        stitch_layout = QtWidgets.QFormLayout()

        self._matching_method = QtWidgets.QComboBox()
        self._matching_method.addItems(["ORB", "SIFT"])
        self._matching_method.setCurrentText(self._config.matching_method)
        stitch_layout.addRow("Matching:", self._matching_method)

        self._fallback_check = QtWidgets.QCheckBox("Fall back to motor position")
        self._fallback_check.setChecked(self._config.fallback_to_position)
        stitch_layout.addRow("", self._fallback_check)

        stitch_group.setLayout(stitch_layout)
        scroll_layout.addWidget(stitch_group)

        # --- Output ---
        output_group = self._create_group("Output")
        output_layout = QtWidgets.QFormLayout()

        dir_layout = QtWidgets.QHBoxLayout()
        self._output_dir = QtWidgets.QLineEdit(self._config.output_directory)
        self._output_dir.setPlaceholderText("Default: ./stitcher_output")
        self._browse_btn = QtWidgets.QPushButton("...")
        self._browse_btn.setMaximumWidth(30)
        dir_layout.addWidget(self._output_dir)
        dir_layout.addWidget(self._browse_btn)
        output_layout.addRow("Directory:", dir_layout)

        self._save_tiles_check = QtWidgets.QCheckBox("Save individual tiles")
        self._save_tiles_check.setChecked(self._config.save_individual_tiles)
        output_layout.addRow("", self._save_tiles_check)

        output_group.setLayout(output_layout)
        scroll_layout.addWidget(output_group)

        # --- Grid Info (read-only) ---
        info_group = self._create_group("Grid Info")
        info_layout = QtWidgets.QFormLayout()

        self._info_grid_size = QtWidgets.QLabel("-")
        info_layout.addRow("Grid:", self._info_grid_size)

        self._info_total_tiles = QtWidgets.QLabel("-")
        info_layout.addRow("Total Tiles:", self._info_total_tiles)

        self._info_fov = QtWidgets.QLabel("-")
        info_layout.addRow("FOV:", self._info_fov)

        self._info_scan_area = QtWidgets.QLabel("-")
        info_layout.addRow("Scan Area:", self._info_scan_area)

        self._info_memory = QtWidgets.QLabel("-")
        info_layout.addRow("Est. Memory:", self._info_memory)

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
        self._z_position.valueChanged.connect(self._on_value_changed)
        self._overlap_slider.valueChanged.connect(self._on_overlap_changed)
        self._exposure.valueChanged.connect(self._on_value_changed)
        self._pixel_size.valueChanged.connect(self._on_value_changed)
        self._img_width.valueChanged.connect(self._on_value_changed)
        self._img_height.valueChanged.connect(self._on_value_changed)
        self._settle_time.valueChanged.connect(self._on_value_changed)
        self._velocity.valueChanged.connect(self._on_value_changed)
        self._matching_method.currentTextChanged.connect(self._on_value_changed)
        self._fallback_check.toggled.connect(self._on_value_changed)
        self._output_dir.textChanged.connect(self._on_value_changed)
        self._save_tiles_check.toggled.connect(self._on_value_changed)

        # Browse button
        self._browse_btn.clicked.connect(self._on_browse)

    def _on_overlap_changed(self, value: int):
        """Handle overlap slider change."""
        self._overlap_label.setText(f"{value}%")
        self._on_value_changed()

    def _on_value_changed(self, *_args):
        """Rebuild ScanConfig from widget values and emit."""
        self._config = ScanConfig(
            corner1=(self._corner1_x.value(), self._corner1_y.value()),
            corner2=(self._corner2_x.value(), self._corner2_y.value()),
            z_position=self._z_position.value(),
            overlap_ratio=self._overlap_slider.value() / 100.0,
            pixel_size_um=self._pixel_size.value(),
            image_width=self._img_width.value(),
            image_height=self._img_height.value(),
            exposure_time_us=self._exposure.value(),
            settle_time_s=self._settle_time.value(),
            velocity_um_s=self._velocity.value(),
            matching_method=self._matching_method.currentText(),
            fallback_to_position=self._fallback_check.isChecked(),
            output_directory=self._output_dir.text(),
            save_individual_tiles=self._save_tiles_check.isChecked(),
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
        self._info_fov.setText(
            f"{cfg.field_of_view_x_um:.0f} x {cfg.field_of_view_y_um:.0f} um"
        )
        self._info_scan_area.setText(
            f"{cfg.scan_range_x:.0f} x {cfg.scan_range_y:.0f} um"
        )
        self._info_memory.setText(f"{cfg.estimated_memory_mb:.1f} MB")

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
        Set a corner position (called from main window after reading XYZ position).

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
        for widget in self.findChildren(
            (
                QtWidgets.QDoubleSpinBox,
                QtWidgets.QSpinBox,
                QtWidgets.QSlider,
                QtWidgets.QComboBox,
                QtWidgets.QCheckBox,
                QtWidgets.QPushButton,
                QtWidgets.QLineEdit,
            )
        ):
            widget.setEnabled(enabled)

    def set_z_enabled(self, enabled: bool):
        """
        Enable or disable the Z Position input.

        Called by the main window when the Z axis connection state changes.
        When disabled, the field is greyed out and its value is ignored
        during scanning (``_move_z`` skips the move when Z is ``None``).
        """
        self._z_position.setEnabled(enabled)
        if enabled:
            self._z_position.setToolTip("")
        else:
            self._z_position.setToolTip("Connect a Z axis to enable this field")
