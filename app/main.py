"""Unified laser platform application entry point."""

import logging
import sys

from PySide6 import QtGui, QtWidgets


def launch(log_level: int = logging.INFO):
    """Launch the unified laser platform application."""
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

    from .gui.main_window import AppMainWindow

    window = AppMainWindow()
    window.show()

    if standalone:
        sys.exit(app.exec())
    else:
        return window


def _apply_dark_palette(app: QtWidgets.QApplication):
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
