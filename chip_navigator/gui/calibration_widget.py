"""
Calibration control panel — manages the calibration workflow.

Provides:
- Status indicator (number of points, solved / not solved, RMSE)
- Table of calibration points with pixel and stage coords
- Buttons: record point, remove point, clear all, solve, save/load
- Mode toggle: calibration mode vs navigation mode
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..mapping.calibration import AffineCalibration

logger = logging.getLogger(__name__)


class CalibrationWidget(QtWidgets.QWidget):
    """
    Side panel for managing affine calibration.

    Signals
    -------
    record_requested()
        User clicked "Record Point" — the main window should read the
        current stage XY position and pair it with the last clicked
        pixel on the panorama.
    solve_requested()
        User clicked "Solve Calibration".
    clear_requested()
        User clicked "Clear All Points".
    remove_requested(int)
        User wants to remove point at given index.
    save_requested()
        User wants to save calibration to file.
    load_requested()
        User wants to load calibration from file.
    mode_changed(str)
        Mode changed to "calibration" or "navigation".
    """

    record_requested = QtCore.Signal()
    solve_requested = QtCore.Signal()
    clear_requested = QtCore.Signal()
    remove_requested = QtCore.Signal(int)
    save_requested = QtCore.Signal()
    load_requested = QtCore.Signal()
    mode_changed = QtCore.Signal(str)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)

        # ---- Mode selector ----
        mode_group = QtWidgets.QGroupBox("Mode")
        mode_layout = QtWidgets.QHBoxLayout(mode_group)

        self._mode_group = QtWidgets.QButtonGroup(self)
        self._cal_radio = QtWidgets.QRadioButton("Calibration")
        self._nav_radio = QtWidgets.QRadioButton("Navigation")
        self._cal_radio.setChecked(True)
        self._mode_group.addButton(self._cal_radio)
        self._mode_group.addButton(self._nav_radio)
        mode_layout.addWidget(self._cal_radio)
        mode_layout.addWidget(self._nav_radio)

        self._cal_radio.toggled.connect(self._on_mode_toggled)

        layout.addWidget(mode_group)

        # ---- Status ----
        status_group = QtWidgets.QGroupBox("Calibration Status")
        status_layout = QtWidgets.QVBoxLayout(status_group)

        self._status_label = QtWidgets.QLabel("Not calibrated")
        self._status_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label)

        self._rmse_label = QtWidgets.QLabel("")
        status_layout.addWidget(self._rmse_label)

        layout.addWidget(status_group)

        # ---- Pending pixel display ----
        self._pending_group = QtWidgets.QGroupBox("Pending Pixel (click on panorama)")
        pending_layout = QtWidgets.QFormLayout(self._pending_group)

        self._pending_u = QtWidgets.QLabel("---")
        self._pending_v = QtWidgets.QLabel("---")
        pending_layout.addRow("U (px):", self._pending_u)
        pending_layout.addRow("V (px):", self._pending_v)

        layout.addWidget(self._pending_group)

        # ---- Record button ----
        self._record_btn = QtWidgets.QPushButton(
            "Record Point (Pixel + Current Stage XY)"
        )
        self._record_btn.setMinimumHeight(36)
        self._record_btn.setStyleSheet("background-color: #1a6b1a; font-weight: bold;")
        self._record_btn.clicked.connect(self.record_requested.emit)
        self._record_btn.setEnabled(False)
        layout.addWidget(self._record_btn)

        # ---- Points table ----
        table_group = QtWidgets.QGroupBox("Calibration Points")
        table_layout = QtWidgets.QVBoxLayout(table_group)

        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["#", "U (px)", "V (px)", "X (um)", "Y (um)"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setMaximumHeight(200)
        table_layout.addWidget(self._table)

        # Table buttons
        table_btn_layout = QtWidgets.QHBoxLayout()
        self._remove_btn = QtWidgets.QPushButton("Remove Selected")
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        table_btn_layout.addWidget(self._remove_btn)

        self._clear_btn = QtWidgets.QPushButton("Clear All")
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        table_btn_layout.addWidget(self._clear_btn)

        table_layout.addLayout(table_btn_layout)
        layout.addWidget(table_group)

        # ---- Solve / Save / Load buttons ----
        action_layout = QtWidgets.QHBoxLayout()

        self._solve_btn = QtWidgets.QPushButton("Solve")
        self._solve_btn.setStyleSheet("font-weight: bold;")
        self._solve_btn.clicked.connect(self.solve_requested.emit)
        action_layout.addWidget(self._solve_btn)

        self._save_btn = QtWidgets.QPushButton("Save")
        self._save_btn.clicked.connect(self.save_requested.emit)
        action_layout.addWidget(self._save_btn)

        self._load_btn = QtWidgets.QPushButton("Load")
        self._load_btn.clicked.connect(self.load_requested.emit)
        action_layout.addWidget(self._load_btn)

        layout.addLayout(action_layout)

        # ---- Navigation info (shown in nav mode) ----
        self._nav_group = QtWidgets.QGroupBox("Navigation")
        nav_layout = QtWidgets.QVBoxLayout(self._nav_group)

        self._nav_info = QtWidgets.QLabel(
            "Click on the panorama to select a target position.\n"
            "The stage will move to the corresponding XY coordinate."
        )
        self._nav_info.setWordWrap(True)
        nav_layout.addWidget(self._nav_info)

        self._target_label = QtWidgets.QLabel("Target: ---")
        self._target_label.setStyleSheet("font-weight: bold;")
        nav_layout.addWidget(self._target_label)

        self._move_btn = QtWidgets.QPushButton("Move to Target")
        self._move_btn.setMinimumHeight(36)
        self._move_btn.setStyleSheet("background-color: #1a4a8b; font-weight: bold;")
        self._move_btn.setEnabled(False)
        nav_layout.addWidget(self._move_btn)

        self._confirm_check = QtWidgets.QCheckBox("Confirm before moving")
        self._confirm_check.setChecked(True)
        nav_layout.addWidget(self._confirm_check)

        layout.addWidget(self._nav_group)

        layout.addStretch()

        # Initial state
        self._update_mode_visibility()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    @property
    def move_button(self) -> QtWidgets.QPushButton:
        """Expose the move button so the main window can connect to it."""
        return self._move_btn

    @property
    def confirm_before_move(self) -> bool:
        return self._confirm_check.isChecked()

    def set_pending_pixel(self, u: float, v: float) -> None:
        """Display the pixel coordinate that was last clicked."""
        self._pending_u.setText(f"{u:.1f}")
        self._pending_v.setText(f"{v:.1f}")
        self._record_btn.setEnabled(True)

    def clear_pending_pixel(self) -> None:
        self._pending_u.setText("---")
        self._pending_v.setText("---")
        self._record_btn.setEnabled(False)

    def update_points_table(self, calibration: AffineCalibration) -> None:
        """Refresh the table from the calibration object."""
        points = calibration.points
        self._table.setRowCount(len(points))
        for i, pt in enumerate(points):
            self._table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(i + 1)))
            self._table.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{pt.pixel_u:.1f}"))
            self._table.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{pt.pixel_v:.1f}"))
            self._table.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{pt.stage_x:.1f}"))
            self._table.setItem(i, 4, QtWidgets.QTableWidgetItem(f"{pt.stage_y:.1f}"))

        self._table.resizeColumnsToContents()

    def update_status(self, calibration: AffineCalibration) -> None:
        """Update the status labels from the calibration object."""
        n = calibration.num_points
        if calibration.is_solved:
            result = calibration.result
            self._status_label.setText(f"Calibrated ({n} points)")
            self._status_label.setStyleSheet(
                "font-weight: bold; font-size: 12px; color: #00dd00;"
            )
            self._rmse_label.setText(
                f"RMSE: {result.rmse:.2f} um\n"
                f"Per-point errors: "
                + ", ".join(f"{e:.1f}" for e in result.per_point_errors)
                + " um"
            )
        else:
            needed = max(0, 3 - n)
            self._status_label.setText(
                f"Not calibrated — {n} point(s) recorded"
                + (f", need {needed} more" if needed > 0 else ", ready to solve")
            )
            self._status_label.setStyleSheet(
                "font-weight: bold; font-size: 12px; color: #ddaa00;"
            )
            self._rmse_label.setText("")

    def set_target_info(
        self,
        pixel_u: float,
        pixel_v: float,
        stage_x: float,
        stage_y: float,
    ) -> None:
        """Show the computed target position."""
        self._target_label.setText(
            f"Target: px({pixel_u:.0f}, {pixel_v:.0f}) "
            f"-> stage({stage_x:.1f}, {stage_y:.1f}) um"
        )
        self._move_btn.setEnabled(True)

    def clear_target_info(self) -> None:
        self._target_label.setText("Target: ---")
        self._move_btn.setEnabled(False)

    @property
    def current_mode(self) -> str:
        return "calibration" if self._cal_radio.isChecked() else "navigation"

    # ------------------------------------------------------------------ #
    #  Internal slots
    # ------------------------------------------------------------------ #

    def _on_mode_toggled(self, checked: bool) -> None:
        self._update_mode_visibility()
        mode = "calibration" if checked else "navigation"
        self.mode_changed.emit(mode)

    def _update_mode_visibility(self) -> None:
        is_cal = self._cal_radio.isChecked()
        self._pending_group.setVisible(is_cal)
        self._record_btn.setVisible(is_cal)
        self._solve_btn.setVisible(is_cal)
        self._nav_group.setVisible(not is_cal)

    def _on_remove_clicked(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if rows:
            self.remove_requested.emit(rows[0].row())
