"""
Progress widget for scan monitoring.

Shows a progress bar, ETA, elapsed time, current tile position,
and scan control buttons (Start, Pause, Resume, Abort).
"""

import logging
import time
from typing import Optional

from PySide6 import QtCore, QtWidgets

logger = logging.getLogger(__name__)


class ProgressWidget(QtWidgets.QWidget):
    """
    Progress and control panel for the scan operation.

    Displays:
    - Progress bar with percentage
    - Current tile position (row, col)
    - Elapsed time
    - Estimated time remaining (ETA)
    - Platform position (X, Y, Z)
    - Start / Pause / Resume / Abort buttons

    Signals
    -------
    start_requested()
        Emitted when the Start button is clicked.
    pause_requested()
        Emitted when the Pause button is clicked.
    resume_requested()
        Emitted when the Resume button is clicked.
    abort_requested()
        Emitted when the Abort button is clicked.
    """

    start_requested = QtCore.Signal()
    pause_requested = QtCore.Signal()
    resume_requested = QtCore.Signal()
    abort_requested = QtCore.Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._scan_start_time: Optional[float] = None
        self._elapsed_timer = QtCore.QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        self._setup_ui()
        self.set_state("idle")

    def _setup_ui(self):
        """Build the progress widget layout."""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # --- Progress bar ---
        progress_layout = QtWidgets.QHBoxLayout()
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setMinimumHeight(22)
        progress_layout.addWidget(self._progress_bar, stretch=1)

        self._tile_label = QtWidgets.QLabel("0 / 0")
        self._tile_label.setMinimumWidth(70)
        progress_layout.addWidget(self._tile_label)

        main_layout.addLayout(progress_layout)

        # --- Info row ---
        info_layout = QtWidgets.QHBoxLayout()

        self._status_label = QtWidgets.QLabel("Idle")
        self._status_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self._status_label)

        info_layout.addStretch()

        self._position_label = QtWidgets.QLabel("Pos: - , - , -")
        info_layout.addWidget(self._position_label)

        info_layout.addSpacing(16)

        self._elapsed_label = QtWidgets.QLabel("Elapsed: --:--")
        info_layout.addWidget(self._elapsed_label)

        self._eta_label = QtWidgets.QLabel("ETA: --:--")
        info_layout.addWidget(self._eta_label)

        main_layout.addLayout(info_layout)

        # --- Control buttons ---
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        self._start_btn = QtWidgets.QPushButton("Start Scan")
        self._start_btn.setMinimumWidth(100)
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #2d8a4e; color: white; font-weight: bold; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #3aa060; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        btn_layout.addWidget(self._start_btn)

        self._pause_btn = QtWidgets.QPushButton("Pause")
        self._pause_btn.setMinimumWidth(80)
        btn_layout.addWidget(self._pause_btn)

        self._resume_btn = QtWidgets.QPushButton("Resume")
        self._resume_btn.setMinimumWidth(80)
        btn_layout.addWidget(self._resume_btn)

        self._abort_btn = QtWidgets.QPushButton("Abort")
        self._abort_btn.setMinimumWidth(80)
        self._abort_btn.setStyleSheet(
            "QPushButton { background-color: #a03030; color: white; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #c04040; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        btn_layout.addWidget(self._abort_btn)

        main_layout.addLayout(btn_layout)

        # --- Connect buttons ---
        self._start_btn.clicked.connect(self.start_requested.emit)
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        self._resume_btn.clicked.connect(self.resume_requested.emit)
        self._abort_btn.clicked.connect(self._on_abort_clicked)

    def _on_abort_clicked(self):
        """Confirm abort before emitting signal."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Abort Scan",
            "Are you sure you want to abort the current scan?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self.abort_requested.emit()

    def set_state(self, state: str):
        """
        Set the widget state and update button visibility/enabled.

        Parameters
        ----------
        state : str
            One of: "idle", "running", "paused", "finished", "error", "aborted"
        """
        self._start_btn.setVisible(state in ("idle", "finished", "error", "aborted"))
        self._start_btn.setEnabled(state in ("idle", "finished", "error", "aborted"))
        self._pause_btn.setVisible(state == "running")
        self._pause_btn.setEnabled(state == "running")
        self._resume_btn.setVisible(state == "paused")
        self._resume_btn.setEnabled(state == "paused")
        self._abort_btn.setVisible(state in ("running", "paused"))
        self._abort_btn.setEnabled(state in ("running", "paused"))

        state_labels = {
            "idle": "Idle",
            "running": "Scanning...",
            "paused": "Paused",
            "finished": "Completed",
            "error": "Error",
            "aborted": "Aborted",
        }
        self._status_label.setText(state_labels.get(state, state))

        # Timer control
        if state == "running":
            if self._scan_start_time is None:
                self._scan_start_time = time.monotonic()
            self._elapsed_timer.start()
        elif state in ("paused",):
            self._elapsed_timer.stop()
        else:
            self._elapsed_timer.stop()

    def update_progress(self, current: int, total: int, status: str):
        """
        Update the progress display.

        Parameters
        ----------
        current : int
            Current tile index (0-based completed count).
        total : int
            Total number of tiles.
        status : str
            Status message string.
        """
        if total > 0:
            pct = int(current / total * 100)
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(pct)
            self._tile_label.setText(f"{current} / {total}")
        if status:
            self._status_label.setText(status)

    def update_position(self, x_um: float, y_um: float, z_um: float):
        """Update the platform position display."""
        self._position_label.setText(f"Pos: {x_um:.0f}, {y_um:.0f}, {z_um:.0f} um")

    def update_eta(self, eta_seconds: float):
        """Update the ETA display."""
        self._eta_label.setText(f"ETA: {self._format_time(eta_seconds)}")

    def reset(self):
        """Reset all progress indicators."""
        self._progress_bar.setValue(0)
        self._tile_label.setText("0 / 0")
        self._elapsed_label.setText("Elapsed: --:--")
        self._eta_label.setText("ETA: --:--")
        self._position_label.setText("Pos: - , - , -")
        self._scan_start_time = None

    def _update_elapsed(self):
        """Update the elapsed time label (called by timer)."""
        if self._scan_start_time is not None:
            elapsed = time.monotonic() - self._scan_start_time
            self._elapsed_label.setText(f"Elapsed: {self._format_time(elapsed)}")

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds into MM:SS or HH:MM:SS string."""
        if seconds < 0:
            return "--:--"
        seconds = int(seconds)
        if seconds < 3600:
            return f"{seconds // 60:02d}:{seconds % 60:02d}"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"
