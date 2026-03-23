"""
Chip Navigator — Application entry point.

Launches the PySide6 GUI for panorama-based chip navigation with
affine calibration mapping.

Usage
-----
Standalone:
    python -m chip_navigator

With pre-configured hardware:
    from chip_navigator.main import launch
    from image_stitcher.acquisition.smc100_axis import SMC100Axis
    from image_stitcher.acquisition.xy_table import XYTable

    x = SMC100Axis("COM11", 1, 1.0)
    y = SMC100Axis("COM11", 2, 1.0)
    xy = XYTable(x, y)

    launch(xy_table=xy)
"""

import logging
import sys
from typing import Optional

from PySide6 import QtGui, QtWidgets

from .gui.chip_navigator_window import ChipNavigatorWindow


def launch(
    xy_table=None,
    camera=None,
    log_level: int = logging.INFO,
):
    """
    Launch the Chip Navigator application.

    Parameters
    ----------
    xy_table : XYTable, optional
        Pre-configured XY table. If None, connect from Hardware menu.
    camera : CameraAdapter, optional
        Pre-configured camera. If None, connect from Hardware menu.
    log_level : int
        Logging level (default: INFO).
    """
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone:
        app = QtWidgets.QApplication(sys.argv)

    app.setStyle("Fusion")
    _apply_dark_palette(app)

    window = ChipNavigatorWindow(xy_table=xy_table, camera=camera)
    window.show()

    if standalone:
        sys.exit(app.exec())
    else:
        return window


def _apply_dark_palette(app):
    """Apply a dark color palette to the application."""
    palette = QtGui.QPalette()

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
