"""
Image Stitcher - Application entry point.

Launches the standalone PySide6 GUI for grid scanning and image stitching.

Usage
-----
Standalone (connect hardware from GUI menus):
    python -m image_stitcher

With pre-configured hardware (from Python):
    from image_stitcher.main import launch
    from image_stitcher.acquisition.smc100_axis import SMC100Axis
    from image_stitcher.acquisition.xy_table import XYTable

    x = SMC100Axis("COM11", 1, 1.0)
    y = SMC100Axis("COM11", 2, 1.0)
    xy = XYTable(x, y)

    launch(xy_table=xy)

Hardware can also be connected at runtime via the Hardware menu:
  - Hardware > Connect XY Table...  (opens dialog to pick COM port / addresses)
  - Hardware > Connect Camera       (auto-detects Allied Vision camera,
                                      starts live preview immediately)
"""

import logging
import sys
from typing import Optional

from PySide6 import QtWidgets

from .gui.main_window import MainWindow
from .acquisition.camera_adapter import CameraAdapter
from .acquisition.xy_table import XYTable


def launch(
    xy_table: Optional[XYTable] = None,
    camera: Optional[CameraAdapter] = None,
    log_level: int = logging.INFO,
):
    """
    Launch the Image Stitcher application.

    Parameters
    ----------
    xy_table : XYTable, optional
        Pre-configured XY table instance. If None, the user can
        connect from the Hardware menu.
    camera : CameraAdapter, optional
        Pre-configured and opened camera adapter. If None, the user
        can connect the camera from the Hardware menu.
    log_level : int
        Logging level (default: INFO).
    """
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Create or reuse QApplication
    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone:
        app = QtWidgets.QApplication(sys.argv)

    # Apply dark theme style
    app.setStyle("Fusion")
    _apply_dark_palette(app)

    # Create and show main window
    window = MainWindow(xy_table=xy_table, camera=camera)
    window.show()

    if standalone:
        sys.exit(app.exec())
    else:
        return window


def _apply_dark_palette(app: QtWidgets.QApplication):
    """Apply a dark color palette to the application."""
    from PySide6 import QtGui

    palette = QtGui.QPalette()

    # Base colors
    dark = QtGui.QColor(45, 45, 45)
    darker = QtGui.QColor(30, 30, 30)
    text = QtGui.QColor(210, 210, 210)
    highlight = QtGui.QColor(42, 130, 218)
    disabled_text = QtGui.QColor(127, 127, 127)

    palette.setColor(QtGui.QPalette.ColorRole.Window, dark)
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, text)
    palette.setColor(QtGui.QPalette.ColorRole.Base, darker)
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, dark)
    palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, dark)
    palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QtGui.QPalette.ColorRole.Text, text)
    palette.setColor(QtGui.QPalette.ColorRole.Button, dark)
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, text)
    palette.setColor(QtGui.QPalette.ColorRole.BrightText, QtGui.QColor(255, 0, 0))
    palette.setColor(QtGui.QPalette.ColorRole.Link, highlight)
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(0, 0, 0))

    # Disabled
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.WindowText,
        disabled_text,
    )
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.Text,
        disabled_text,
    )
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.ButtonText,
        disabled_text,
    )

    app.setPalette(palette)


if __name__ == "__main__":
    launch()
