"""Hardware controller: XY table + camera connect/disconnect (no UI widget)."""

import logging

from PySide6 import QtCore, QtWidgets

from image_stitcher.acquisition.camera_adapter import CameraAdapter
from image_stitcher.gui.main_window import XYConnectDialog

from ..session import AppSession
from ..i18n import tr

logger = logging.getLogger(__name__)

_COLOR_OK = _COLOR_OK
_COLOR_ERR = _COLOR_ERR


class HardwarePanel(QtCore.QObject):
    """Logic-only controller for shared hardware connections.

    No UI widgets. Call connect_xy() / disconnect_xy() / connect_camera() /
    disconnect_camera() from menu actions.

    Signals
    -------
    hardware_changed()
        Emitted whenever XY or camera connection state changes.
    xy_status_changed(text, color)
        Emitted with updated status label text and CSS colour string.
    cam_status_changed(text, color)
        Emitted with updated status label text and CSS colour string.
    pos_updated(text)
        Emitted every 500 ms while XY is connected with position string.
    """

    hardware_changed = QtCore.Signal()
    xy_status_changed = QtCore.Signal(str, str)   # (text, css_color)
    cam_status_changed = QtCore.Signal(str, str)  # (text, css_color)
    pos_updated = QtCore.Signal(str)

    def __init__(self, session: AppSession, parent=None):
        super().__init__(parent)
        self._session = session

        self._pos_timer = QtCore.QTimer(self)
        self._pos_timer.setInterval(500)
        self._pos_timer.timeout.connect(self._update_position)

    # ------------------------------------------------------------------ #
    #  XY Table
    # ------------------------------------------------------------------ #

    def connect_xy(self, parent_widget: QtWidgets.QWidget):
        if self._session.xy_table is not None:
            QtWidgets.QMessageBox.information(parent_widget, tr("hw.xy"), tr("hw.connected"))
            return

        dlg = XYConnectDialog(parent_widget)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._session.xy_table = dlg.create_xy_table()
            self._emit_xy_status()
            self._pos_timer.start()
            self.hardware_changed.emit()
            logger.info("XY table connected.")
        except Exception as e:
            self._session.xy_table = None
            QtWidgets.QMessageBox.critical(
                parent_widget, tr("hw.xy"), f"{tr('hw.connect')} failed:\n\n{e}"
            )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def disconnect_xy(self):
        if self._session.xy_table is None:
            return
        self._pos_timer.stop()
        try:
            self._session.xy_table.close()
        except Exception as e:
            logger.warning(f"Error closing XY: {e}")
        self._session.xy_table = None
        self._emit_xy_status()
        self.pos_updated.emit(tr("hw.pos_placeholder"))
        self.hardware_changed.emit()
        logger.info("XY table disconnected.")

    def is_xy_connected(self) -> bool:
        return self._session.xy_table is not None

    def _emit_xy_status(self):
        if self._session.xy_table is not None:
            xy = self._session.xy_table
            text = tr("hw.connected_z") if xy.has_z else tr("hw.connected")
            self.xy_status_changed.emit(text, _COLOR_OK)
        else:
            self.xy_status_changed.emit(tr("hw.disconnected"), _COLOR_ERR)

    def _update_position(self):
        if self._session.xy_table is None:
            return
        try:
            x, y = self._session.xy_table.update_position()
            z = self._session.xy_table.update_position_z()
            z_text = f"  Z: {z:.1f}" if z is not None else ""
            self.pos_updated.emit(f"X: {x:.1f}  Y: {y:.1f}{z_text} µm")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Camera
    # ------------------------------------------------------------------ #

    def connect_camera(self, parent_widget: QtWidgets.QWidget):
        if self._session.camera is not None and self._session.camera.is_open:
            QtWidgets.QMessageBox.information(parent_widget, tr("hw.camera"), tr("hw.connected"))
            return

        try:
            cam = CameraAdapter()
            cam.open()
            cam.configure(exposure_us=1000.0, auto_exposure=True)
            self._session.camera = cam
            self._emit_cam_status()
            self.hardware_changed.emit()
            logger.info(f"Camera connected: {cam.camera_name}")
        except Exception as e:
            self._session.camera = None
            QtWidgets.QMessageBox.critical(
                parent_widget, tr("hw.camera"), f"{tr('hw.connect')} failed:\n\n{e}"
            )

    def disconnect_camera(self):
        if self._session.camera is None:
            return
        try:
            self._session.camera.close()
        except Exception as e:
            logger.warning(f"Error closing camera: {e}")
        self._session.camera = None
        self._emit_cam_status()
        self.hardware_changed.emit()
        logger.info("Camera disconnected.")

    def is_camera_connected(self) -> bool:
        cam = self._session.camera
        return cam is not None and cam.is_open

    def refresh_status(self):
        """Re-emit current XY and camera status signals (e.g. after language change)."""
        self._emit_xy_status()
        self._emit_cam_status()

    def _emit_cam_status(self):
        cam = self._session.camera
        if cam is not None and cam.is_open:
            self.cam_status_changed.emit(f"● {cam.camera_name}", _COLOR_OK)
        else:
            self.cam_status_changed.emit(tr("hw.disconnected"), _COLOR_ERR)
