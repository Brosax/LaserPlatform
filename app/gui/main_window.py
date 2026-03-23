"""Main application window: step indicator, three stages, hardware + language menus."""

import logging
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..session import AppSession
from ..i18n import tr, language_manager, LanguageManager
from .hardware_panel import HardwarePanel
from .step_indicator import StepIndicator
from .stages.scan_stage import ScanStage
from .stages.stitch_stage import StitchStage
from .stages.navigate_stage import NavigateStage

logger = logging.getLogger(__name__)


class AppMainWindow(QtWidgets.QMainWindow):
    """
    Unified laser platform application window.

    Layout:
    +--------------------------------------------------+
    | MenuBar: [Hardware]  [Language]                  |
    +--------------------------------------------------+
    | [ ① Scan & Acquire ] ─── [ ② Stitching ] ─── [ ③ ] |
    +--------------------------------------------------+
    |        QStackedWidget (full width)               |
    |  ScanStage / StitchStage / NavigateStage         |
    +--------------------------------------------------+
    | StatusBar: XY ● ...  Cam ● ...  X:... Y:...     |
    +--------------------------------------------------+
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._session = AppSession()
        self._setup_ui()
        self._connect_signals()

        self.setWindowTitle(tr("app.title"))
        self.resize(1400, 900)

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # --- Step indicator (top) ---
        self._step_indicator = StepIndicator()
        root_layout.addWidget(self._step_indicator)

        # --- Stacked stages (full width) ---
        self._stacked = QtWidgets.QStackedWidget()

        self._hardware = HardwarePanel(self._session, parent=self)

        self._scan_stage = ScanStage(self._session)
        self._stitch_stage = StitchStage()
        self._navigate_stage = NavigateStage(self._session)

        self._stacked.addWidget(self._scan_stage)
        self._stacked.addWidget(self._stitch_stage)
        self._stacked.addWidget(self._navigate_stage)

        root_layout.addWidget(self._stacked, stretch=1)

        # --- Status bar: hardware status + position ---
        self._sb_xy = QtWidgets.QLabel()
        self._sb_cam = QtWidgets.QLabel()
        self._sb_pos = QtWidgets.QLabel()
        self._sb_pos.setStyleSheet("font-family: monospace;")
        for lbl in (self._sb_xy, self._sb_cam, self._sb_pos):
            lbl.setContentsMargins(6, 0, 6, 0)
            self.statusBar().addWidget(lbl)
        self.statusBar().addWidget(QtWidgets.QLabel(), 1)  # spacer

        # --- Menu bar ---
        self._setup_menu()

        # Initialise status bar labels
        self._on_xy_status(tr("hw.disconnected"), "#cc4444")
        self._on_cam_status(tr("hw.disconnected"), "#cc4444")
        self._sb_pos.setText(tr("hw.pos_placeholder"))

    def _setup_menu(self):
        # Hardware menu
        self._hw_menu = self.menuBar().addMenu(tr("menu.hardware"))

        self._xy_menu = self._hw_menu.addMenu(tr("hw.xy"))
        self._act_xy_connect = self._xy_menu.addAction(tr("hw.connect"))
        self._act_xy_connect.triggered.connect(
            lambda: self._hardware.connect_xy(self)
        )
        self._act_xy_disconnect = self._xy_menu.addAction(tr("hw.disconnect"))
        self._act_xy_disconnect.setEnabled(False)
        self._act_xy_disconnect.triggered.connect(self._hardware.disconnect_xy)

        self._cam_menu = self._hw_menu.addMenu(tr("hw.camera"))
        self._act_cam_connect = self._cam_menu.addAction(tr("hw.connect"))
        self._act_cam_connect.triggered.connect(
            lambda: self._hardware.connect_camera(self)
        )
        self._act_cam_disconnect = self._cam_menu.addAction(tr("hw.disconnect"))
        self._act_cam_disconnect.setEnabled(False)
        self._act_cam_disconnect.triggered.connect(self._hardware.disconnect_camera)

        # Language menu
        self._lang_menu = self.menuBar().addMenu(tr("menu.language"))
        for code, name in LanguageManager.LANGUAGES.items():
            action = self._lang_menu.addAction(name)
            action.triggered.connect(lambda _, c=code: language_manager().set_language(c))

    def _connect_signals(self):
        # Step indicator -> switch view
        self._step_indicator.step_clicked.connect(self._on_step_clicked)
        self._stacked.currentChanged.connect(self._on_stage_switched)

        # Hardware controller -> update UI
        self._hardware.hardware_changed.connect(self._on_hardware_changed)
        self._hardware.xy_status_changed.connect(self._on_xy_status)
        self._hardware.cam_status_changed.connect(self._on_cam_status)
        self._hardware.pos_updated.connect(self._sb_pos.setText)

        # Stage transitions
        self._scan_stage.scan_finished.connect(self._on_scan_done)
        self._stitch_stage.stitch_exported.connect(self._on_stitch_done)

        # Language changes -> retranslate window
        language_manager().language_changed.connect(self._retranslate_ui)

    # ------------------------------------------------------------------ #
    #  Hardware status display
    # ------------------------------------------------------------------ #

    @QtCore.Slot(str, str)
    def _on_xy_status(self, text: str, color: str):
        self._sb_xy.setText(f"{tr('hw.xy')}: {text}")
        self._sb_xy.setStyleSheet(f"color: {color};")
        connected = self._hardware.is_xy_connected()
        self._act_xy_connect.setEnabled(not connected)
        self._act_xy_disconnect.setEnabled(connected)

    @QtCore.Slot(str, str)
    def _on_cam_status(self, text: str, color: str):
        self._sb_cam.setText(f"{tr('hw.camera')}: {text}")
        self._sb_cam.setStyleSheet(f"color: {color};")
        connected = self._hardware.is_camera_connected()
        self._act_cam_connect.setEnabled(not connected)
        self._act_cam_disconnect.setEnabled(connected)

    @QtCore.Slot()
    def _retranslate_ui(self):
        self.setWindowTitle(tr("app.title"))
        self._hw_menu.setTitle(tr("menu.hardware"))
        self._xy_menu.setTitle(tr("hw.xy"))
        self._cam_menu.setTitle(tr("hw.camera"))
        self._lang_menu.setTitle(tr("menu.language"))
        self._act_xy_connect.setText(tr("hw.connect"))
        self._act_xy_disconnect.setText(tr("hw.disconnect"))
        self._act_cam_connect.setText(tr("hw.connect"))
        self._act_cam_disconnect.setText(tr("hw.disconnect"))
        self._hardware.refresh_status()

    # ------------------------------------------------------------------ #
    #  Step navigation
    # ------------------------------------------------------------------ #

    @QtCore.Slot(int)
    def _on_step_clicked(self, index: int):
        self._stacked.setCurrentIndex(index)

    @QtCore.Slot(int)
    def _on_stage_switched(self, new_index: int):
        """Stop live feed on all stages; start it only on the newly active one."""
        self._scan_stage.on_stage_leave()
        self._navigate_stage.on_stage_leave()
        if new_index == 0:
            self._scan_stage.on_stage_enter()
        elif new_index == 2:
            self._navigate_stage.on_stage_enter()

    # ------------------------------------------------------------------ #
    #  Hardware propagation to stages
    # ------------------------------------------------------------------ #

    @QtCore.Slot()
    def _on_hardware_changed(self):
        self._scan_stage.on_hardware_changed()
        self._navigate_stage.on_hardware_changed()
        # Start feed on the currently visible stage if camera just connected
        self._on_stage_switched(self._stacked.currentIndex())

    # ------------------------------------------------------------------ #
    #  Stage transitions
    # ------------------------------------------------------------------ #

    @QtCore.Slot(str)
    def _on_scan_done(self, output_path: str):
        self._session.scan_output_dir = Path(output_path)
        self._stitch_stage.set_input_dir(Path(output_path))
        self._step_indicator.set_step(1)
        self._stacked.setCurrentIndex(1)
        logger.info(f"Scan done -> switched to stitch stage, input: {output_path}")

    @QtCore.Slot(str)
    def _on_stitch_done(self, panorama_path: str):
        self._session.panorama_path = Path(panorama_path)
        self._navigate_stage.load_panorama(panorama_path)
        self._step_indicator.set_step(2)
        self._stacked.setCurrentIndex(2)
        logger.info(f"Stitch exported -> auto-loading panorama {panorama_path}")

    # ------------------------------------------------------------------ #
    #  Window lifecycle
    # ------------------------------------------------------------------ #

    def closeEvent(self, event: QtGui.QCloseEvent):
        self._scan_stage.stop_all()
        self._navigate_stage.stop_all()
        self._hardware.disconnect_camera()
        self._hardware.disconnect_xy()
        event.accept()
