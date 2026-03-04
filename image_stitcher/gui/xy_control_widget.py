"""
XY movement control widget.

Provides:
- Current position display (auto-refreshing)
- Jog buttons (arrows) with selectable step size
- Move-to-absolute-position fields
- Homing button
- Halt (emergency stop) button

All blocking motor operations run in a QThread so the GUI stays
responsive.
"""

import logging
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)


class _MoveWorker(QtCore.QThread):
    """Runs a blocking motor operation in a background thread."""

    finished_ok = QtCore.Signal()
    error_occurred = QtCore.Signal(str)

    def __init__(self, func, *args, parent=None):
        super().__init__(parent)
        self._func = func
        self._args = args

    def run(self):
        try:
            self._func(*self._args)
            self.finished_ok.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))


class XYControlWidget(QtWidgets.QGroupBox):
    """
    Panel for manual XY stage control.

    Signals
    -------
    position_changed(float, float)
        Emitted after every completed move with (x_um, y_um).
    """

    position_changed = QtCore.Signal(float, float)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__("XY Control", parent)
        self._xy = None  # XYTable instance (set via set_xy_table)
        self._worker: Optional[_MoveWorker] = None

        self._setup_ui()
        self.setEnabled(False)  # disabled until hardware is connected

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)

        # ---- Current position display ----
        pos_layout = QtWidgets.QHBoxLayout()
        pos_layout.addWidget(QtWidgets.QLabel("Position:"))
        self._pos_label = QtWidgets.QLabel("X: ---  Y: ---")
        self._pos_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        pos_layout.addWidget(self._pos_label, stretch=1)
        self._refresh_btn = QtWidgets.QPushButton("Refresh")
        self._refresh_btn.setMaximumWidth(60)
        self._refresh_btn.clicked.connect(self._refresh_position)
        pos_layout.addWidget(self._refresh_btn)
        layout.addLayout(pos_layout)

        # ---- Jog step size ----
        step_layout = QtWidgets.QHBoxLayout()
        step_layout.addWidget(QtWidgets.QLabel("Step:"))
        self._step_size = QtWidgets.QComboBox()
        self._step_size.addItems(["1", "5", "10", "50", "100", "500", "1000", "5000"])
        self._step_size.setCurrentText("100")
        self._step_size.setEditable(True)
        step_layout.addWidget(self._step_size)
        step_layout.addWidget(QtWidgets.QLabel("um"))
        step_layout.addStretch()
        layout.addLayout(step_layout)

        # ---- Jog buttons (arrow pad) ----
        #
        #         [  Y+  ]
        #  [ X- ] [  *  ] [ X+ ]
        #         [  Y-  ]
        #
        jog_grid = QtWidgets.QGridLayout()
        jog_grid.setSpacing(4)

        self._btn_yp = QtWidgets.QPushButton("Y+")
        self._btn_ym = QtWidgets.QPushButton("Y-")
        self._btn_xp = QtWidgets.QPushButton("X+")
        self._btn_xm = QtWidgets.QPushButton("X-")

        btn_size = 55
        for btn in (self._btn_yp, self._btn_ym, self._btn_xp, self._btn_xm):
            btn.setFixedSize(btn_size, btn_size)

        jog_grid.addWidget(self._btn_yp, 0, 1, QtCore.Qt.AlignmentFlag.AlignCenter)
        jog_grid.addWidget(self._btn_xm, 1, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
        jog_grid.addWidget(self._btn_xp, 1, 2, QtCore.Qt.AlignmentFlag.AlignCenter)
        jog_grid.addWidget(self._btn_ym, 2, 1, QtCore.Qt.AlignmentFlag.AlignCenter)

        # Center spacer
        center_label = QtWidgets.QLabel("")
        center_label.setFixedSize(btn_size, btn_size)
        center_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        jog_grid.addWidget(center_label, 1, 1, QtCore.Qt.AlignmentFlag.AlignCenter)

        jog_container = QtWidgets.QHBoxLayout()
        jog_container.addStretch()
        jog_container.addLayout(jog_grid)
        jog_container.addStretch()
        layout.addLayout(jog_container)

        self._btn_xp.clicked.connect(lambda: self._jog("x", +1))
        self._btn_xm.clicked.connect(lambda: self._jog("x", -1))
        self._btn_yp.clicked.connect(lambda: self._jog("y", +1))
        self._btn_ym.clicked.connect(lambda: self._jog("y", -1))

        # ---- Move to absolute position ----
        move_group = QtWidgets.QGroupBox("Move To")
        move_layout = QtWidgets.QFormLayout(move_group)

        self._target_x = QtWidgets.QDoubleSpinBox()
        self._target_x.setRange(-1e6, 1e6)
        self._target_x.setDecimals(1)
        self._target_x.setSuffix(" um")
        move_layout.addRow("X:", self._target_x)

        self._target_y = QtWidgets.QDoubleSpinBox()
        self._target_y.setRange(-1e6, 1e6)
        self._target_y.setDecimals(1)
        self._target_y.setSuffix(" um")
        move_layout.addRow("Y:", self._target_y)

        move_btn_layout = QtWidgets.QHBoxLayout()
        self._move_btn = QtWidgets.QPushButton("Move")
        self._move_btn.clicked.connect(self._on_move_to)
        move_btn_layout.addWidget(self._move_btn)

        self._move_x_btn = QtWidgets.QPushButton("Move X only")
        self._move_x_btn.clicked.connect(self._on_move_x_only)
        move_btn_layout.addWidget(self._move_x_btn)

        self._move_y_btn = QtWidgets.QPushButton("Move Y only")
        self._move_y_btn.clicked.connect(self._on_move_y_only)
        move_btn_layout.addWidget(self._move_y_btn)

        move_layout.addRow(move_btn_layout)
        layout.addWidget(move_group)

        # ---- Homing + Halt ----
        bottom_layout = QtWidgets.QHBoxLayout()

        self._home_btn = QtWidgets.QPushButton("Home XY")
        self._home_btn.clicked.connect(self._on_homing)
        bottom_layout.addWidget(self._home_btn)

        bottom_layout.addStretch()

        self._halt_btn = QtWidgets.QPushButton("HALT")
        self._halt_btn.setStyleSheet(
            "background-color: #cc0000; color: white; font-weight: bold;"
        )
        self._halt_btn.clicked.connect(self._on_halt)
        bottom_layout.addWidget(self._halt_btn)

        layout.addLayout(bottom_layout)

    # ------------------------------------------------------------------ #
    #  Public interface
    # ------------------------------------------------------------------ #

    def set_xy_table(self, xy) -> None:
        """
        Attach an XYTable instance. Enables the widget and refreshes
        the position display.

        Parameters
        ----------
        xy : XYTable or None
            Pass ``None`` to detach and disable the widget.
        """
        self._xy = xy
        self.setEnabled(xy is not None)
        if xy is not None:
            self._refresh_position()

    # ------------------------------------------------------------------ #
    #  Jog
    # ------------------------------------------------------------------ #

    def _get_step(self) -> float:
        """Return the currently selected step size in um."""
        try:
            return float(self._step_size.currentText())
        except ValueError:
            return 100.0

    def _jog(self, axis: str, direction: int):
        """Start a jog move on the given axis."""
        if self._xy is None or self._is_busy():
            return
        step = self._get_step() * direction
        if axis == "x":
            self._run_in_thread(self._xy.jog_x, step)
        else:
            self._run_in_thread(self._xy.jog_y, step)

    # ------------------------------------------------------------------ #
    #  Move to
    # ------------------------------------------------------------------ #

    def _on_move_to(self):
        if self._xy is None or self._is_busy():
            return
        x = self._target_x.value()
        y = self._target_y.value()
        self._run_in_thread(self._xy.move_to, x, y)

    def _on_move_x_only(self):
        if self._xy is None or self._is_busy():
            return
        self._run_in_thread(self._xy.move_x, self._target_x.value())

    def _on_move_y_only(self):
        if self._xy is None or self._is_busy():
            return
        self._run_in_thread(self._xy.move_y, self._target_y.value())

    # ------------------------------------------------------------------ #
    #  Homing / Halt
    # ------------------------------------------------------------------ #

    def _on_homing(self):
        if self._xy is None or self._is_busy():
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Homing",
            "Run homing on both X and Y axes?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._run_in_thread(self._xy.homing)

    def _on_halt(self):
        """Emergency stop — runs synchronously (fast command)."""
        if self._xy is not None:
            try:
                self._xy.halt()
            except Exception as e:
                logger.error(f"Halt error: {e}")

    # ------------------------------------------------------------------ #
    #  Position refresh
    # ------------------------------------------------------------------ #

    def _refresh_position(self):
        """Read current position from hardware and update the display."""
        if self._xy is None:
            return
        try:
            x, y = self._xy.update_position()
            self._update_pos_display(x, y)
        except Exception as e:
            logger.warning(f"Position refresh failed: {e}")
            self._pos_label.setText("X: ???  Y: ???")

    def _update_pos_display(self, x_um: float, y_um: float):
        self._pos_label.setText(f"X: {x_um:.1f}  Y: {y_um:.1f} um")
        self.position_changed.emit(x_um, y_um)

    # ------------------------------------------------------------------ #
    #  Thread management
    # ------------------------------------------------------------------ #

    def _is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _run_in_thread(self, func, *args):
        """Run a blocking motor function in a background thread."""
        self._set_buttons_enabled(False)
        self._worker = _MoveWorker(func, *args, parent=self)
        self._worker.finished_ok.connect(self._on_move_done)
        self._worker.error_occurred.connect(self._on_move_error)
        self._worker.start()

    def _on_move_done(self):
        self._set_buttons_enabled(True)
        self._refresh_position()
        self._worker = None

    def _on_move_error(self, msg: str):
        self._set_buttons_enabled(True)
        self._refresh_position()
        self._worker = None
        QtWidgets.QMessageBox.warning(self, "Move Error", msg)

    def _set_buttons_enabled(self, enabled: bool):
        """Enable/disable all motion buttons (HALT always stays enabled)."""
        for btn in (
            self._btn_xp,
            self._btn_xm,
            self._btn_yp,
            self._btn_ym,
            self._move_btn,
            self._move_x_btn,
            self._move_y_btn,
            self._home_btn,
            self._refresh_btn,
        ):
            btn.setEnabled(enabled)
