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
        hw_menu = self.menuBar().addMenu(tr("menu.hardware"))

        xy_menu = hw_menu.addMenu(tr("hw.xy"))
        self._act_xy_connect = xy_menu.addAction(tr("hw.connect"))
        self._act_xy_connect.triggered.connect(
            lambda: self._hardware.connect_xy(self)
        )
        self._act_xy_disconnect = xy_menu.addAction(tr("hw.disconnect"))
        self._act_xy_disconnect.setEnabled(False)
        self._act_xy_disconnect.triggered.connect(self._hardware.disconnect_xy)

        cam_menu = hw_menu.addMenu(tr("hw.camera"))
        self._act_cam_connect = cam_menu.addAction(tr("hw.connect"))
        self._act_cam_connect.triggered.connect(
            lambda: self._hardware.connect_camera(self)
        )
        self._act_cam_disconnect = cam_menu.addAction(tr("hw.disconnect"))
        self._act_cam_disconnect.setEnabled(False)
        self._act_cam_disconnect.triggered.connect(self._hardware.disconnect_camera)

        # Language menu
        lang_menu = self.menuBar().addMenu(tr("menu.language"))
        for code, name in LanguageManager.LANGUAGES.items():
            action = lang_menu.addAction(name)
            action.triggered.connect(lambda _, c=code: language_manager().set_language(c))

    def _connect_signals(self):
        # Step indicator -> switch view
        self._step_indicator.step_clicked.connect(self._on_step_clicked)

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
        # Rebuild menu bar titles
        menu_bar = self.menuBar()
        actions = menu_bar.actions()
        if len(actions) >= 1:
            actions[0].setText(tr("menu.hardware"))
            # Update submenu titles
            hw_menu = actions[0].menu()
            if hw_menu:
                sub_actions = hw_menu.actions()
                if len(sub_actions) >= 1 and sub_actions[0].menu():
                    sub_actions[0].setText(tr("hw.xy"))
                if len(sub_actions) >= 2 and sub_actions[1].menu():
                    sub_actions[1].setText(tr("hw.camera"))
                # Update connect/disconnect action text
                self._act_xy_connect.setText(tr("hw.connect"))
                self._act_xy_disconnect.setText(tr("hw.disconnect"))
                self._act_cam_connect.setText(tr("hw.connect"))
                self._act_cam_disconnect.setText(tr("hw.disconnect"))
        if len(actions) >= 2:
            actions[1].setText(tr("menu.language"))
        # Refresh status bar labels
        self._on_xy_status(
            *((tr("hw.connected_z") if (self._session.xy_table and self._session.xy_table.has_z)
               else tr("hw.connected"), "#44cc44")
              if self._hardware.is_xy_connected()
              else (tr("hw.disconnected"), "#cc4444"))
        )
        self._on_cam_status(
            *(
                (f"● {self._session.camera.camera_name}", "#44cc44")
                if self._hardware.is_camera_connected()
                else (tr("hw.disconnected"), "#cc4444")
            )
        )

    # ------------------------------------------------------------------ #
    #  Step navigation
    # ------------------------------------------------------------------ #

    @QtCore.Slot(int)
    def _on_step_clicked(self, index: int):
        self._stacked.setCurrentIndex(index)

    # ------------------------------------------------------------------ #
    #  Hardware propagation to stages
    # ------------------------------------------------------------------ #

    @QtCore.Slot()
    def _on_hardware_changed(self):
        self._scan_stage.on_hardware_changed()
        self._navigate_stage.on_hardware_changed()

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

        if self._session.camera is not None and self._session.camera.is_open:
            try:
                self._session.camera.close()
            except Exception as e:
                logger.warning(f"Error closing camera on exit: {e}")

        if self._session.xy_table is not None:
            try:
                self._session.xy_table.close()
            except Exception as e:
                logger.warning(f"Error closing XY table on exit: {e}")

        event.accept()
