"""
Real-time stitching preview widget.

Displays either a **live camera feed** (continuously-updating single frame)
or the **composite image** as it is being built, with an optional grid
overlay showing tile boundaries and current scan position.
"""

import logging
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)


class PreviewWidget(QtWidgets.QWidget):
    """
    Widget that displays either a live camera feed or a stitching composite.

    Features:
    - Two modes: **live** (real-time camera) and **composite** (scan result)
    - Auto-scaling to fit the widget while preserving aspect ratio
    - Crosshair overlay in live mode
    - Optional grid overlay showing tile boundaries (composite mode)
    - Current position indicator (composite mode)
    - Mouse-wheel zoom and pan (click-drag)
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._pixmap: Optional[QtGui.QPixmap] = None
        self._grid_info: Optional[dict] = None
        self._current_tile: Optional[tuple[int, int]] = None
        self._show_grid = True
        self._show_crosshair = True
        self._zoom_factor = 1.0
        self._pan_offset = QtCore.QPointF(0, 0)
        self._last_mouse_pos: Optional[QtCore.QPoint] = None
        self._is_panning = False

        # View mode: "live" or "composite"
        self._mode = "live"

        # Layout
        self._setup_ui()

        # Minimum size
        self.setMinimumSize(400, 300)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

    def _setup_ui(self):
        """Set up the widget UI."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()

        # Mode toggle
        self._mode_combo = QtWidgets.QComboBox()
        self._mode_combo.addItem("Live", "live")
        self._mode_combo.addItem("Composite", "composite")
        self._mode_combo.setCurrentIndex(0)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._mode_combo.setToolTip(
            "Switch between live camera view and composite preview"
        )
        toolbar.addWidget(QtWidgets.QLabel("View:"))
        toolbar.addWidget(self._mode_combo)

        toolbar.addSpacing(8)

        # Crosshair toggle (live mode only)
        self._crosshair_checkbox = QtWidgets.QCheckBox("Crosshair")
        self._crosshair_checkbox.setChecked(True)
        self._crosshair_checkbox.toggled.connect(self._on_crosshair_toggled)
        toolbar.addWidget(self._crosshair_checkbox)

        # Grid toggle (composite mode only)
        self._grid_checkbox = QtWidgets.QCheckBox("Show Grid")
        self._grid_checkbox.setChecked(True)
        self._grid_checkbox.toggled.connect(self._on_grid_toggled)
        toolbar.addWidget(self._grid_checkbox)

        toolbar.addSpacing(8)

        self._fit_btn = QtWidgets.QPushButton("Fit")
        self._fit_btn.setMaximumWidth(60)
        self._fit_btn.clicked.connect(self._fit_to_view)
        toolbar.addWidget(self._fit_btn)

        self._zoom_label = QtWidgets.QLabel("100%")
        self._zoom_label.setMinimumWidth(50)
        toolbar.addWidget(self._zoom_label)

        self._info_label = QtWidgets.QLabel("No image")
        toolbar.addStretch()
        toolbar.addWidget(self._info_label)

        layout.addLayout(toolbar)

        # Image display area (we paint directly on this widget)
        self._canvas_widget = _CanvasArea(self)
        layout.addWidget(self._canvas_widget, stretch=1)

        # Initial toolbar state
        self._update_toolbar_visibility()

    # ------------------------------------------------------------------ #
    #  Mode management
    # ------------------------------------------------------------------ #

    def set_mode(self, mode: str):
        """
        Switch between 'live' and 'composite' modes.

        Parameters
        ----------
        mode : str
            Either ``'live'`` or ``'composite'``.
        """
        if mode not in ("live", "composite"):
            return
        self._mode = mode
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(idx)
            self._mode_combo.blockSignals(False)
        self._update_toolbar_visibility()
        self._canvas_widget.update()

    def _on_mode_changed(self, index: int):
        """Handle mode combo box change."""
        self._mode = self._mode_combo.currentData()
        self._update_toolbar_visibility()
        self._canvas_widget.update()

    def _update_toolbar_visibility(self):
        """Show/hide toolbar items based on current mode."""
        is_live = self._mode == "live"
        self._crosshair_checkbox.setVisible(is_live)
        self._grid_checkbox.setVisible(not is_live)

    # ------------------------------------------------------------------ #
    #  Live feed
    # ------------------------------------------------------------------ #

    def update_live_frame(self, frame: np.ndarray):
        """
        Update the preview with a new live camera frame.

        Parameters
        ----------
        frame : np.ndarray
            Raw frame from the camera (typically uint16, Mono14 data).
        """
        if frame is None or frame.size == 0:
            return

        # Convert to uint8 for display
        if frame.dtype == np.uint16:
            # Mono14: 14-bit data in uint16 container -> shift right by 6
            display = (frame >> 6).astype(np.uint8)
        elif frame.dtype == np.uint8:
            display = frame
        else:
            # Normalize to uint8
            fmin, fmax = frame.min(), frame.max()
            if fmax > fmin:
                display = ((frame - fmin) / (fmax - fmin) * 255).astype(np.uint8)
            else:
                display = np.zeros(frame.shape[:2], dtype=np.uint8)

        h, w = display.shape[:2]
        qimage = QtGui.QImage(
            display.data.tobytes(),
            w,
            h,
            w,
            QtGui.QImage.Format.Format_Grayscale8,
        )
        self._pixmap = QtGui.QPixmap.fromImage(qimage)
        self._info_label.setText(f"Live: {w} x {h} px")
        self._canvas_widget.update()

    # ------------------------------------------------------------------ #
    #  Composite preview (existing interface)
    # ------------------------------------------------------------------ #

    def update_preview(self, image: np.ndarray):
        """
        Update the preview with a new composite image.

        Parameters
        ----------
        image : np.ndarray
            uint8 grayscale preview image.
        """
        if image is None or image.size == 0:
            return

        h, w = image.shape[:2]

        # Convert numpy array to QPixmap
        if image.ndim == 2:
            qimage = QtGui.QImage(
                image.data.tobytes(),
                w,
                h,
                w,
                QtGui.QImage.Format.Format_Grayscale8,
            )
        else:
            qimage = QtGui.QImage(
                image.data.tobytes(),
                w,
                h,
                w * 3,
                QtGui.QImage.Format.Format_RGB888,
            )

        self._pixmap = QtGui.QPixmap.fromImage(qimage)
        self._info_label.setText(f"{w} x {h} px")
        self._canvas_widget.update()

    def set_grid_info(self, num_rows: int, num_cols: int):
        """
        Set grid dimensions for the overlay.

        Parameters
        ----------
        num_rows : int
            Number of rows in the grid.
        num_cols : int
            Number of columns in the grid.
        """
        self._grid_info = {"rows": num_rows, "cols": num_cols}
        self._canvas_widget.update()

    def set_current_tile(self, row: int, col: int):
        """
        Highlight the current tile being captured.

        Parameters
        ----------
        row : int
            Current row index.
        col : int
            Current column index.
        """
        self._current_tile = (row, col)
        self._canvas_widget.update()

    def clear(self):
        """Clear the preview."""
        self._pixmap = None
        self._grid_info = None
        self._current_tile = None
        self._zoom_factor = 1.0
        self._pan_offset = QtCore.QPointF(0, 0)
        self._info_label.setText("No image")
        self._zoom_label.setText("100%")
        self._canvas_widget.update()

    # ------------------------------------------------------------------ #
    #  Toolbar handlers
    # ------------------------------------------------------------------ #

    def _on_crosshair_toggled(self, checked: bool):
        self._show_crosshair = checked
        self._canvas_widget.update()

    def _on_grid_toggled(self, checked: bool):
        self._show_grid = checked
        self._canvas_widget.update()

    def _fit_to_view(self):
        self._zoom_factor = 1.0
        self._pan_offset = QtCore.QPointF(0, 0)
        self._zoom_label.setText("100%")
        self._canvas_widget.update()

    def get_paint_params(self):
        """Return current state for painting by _CanvasArea."""
        return {
            "pixmap": self._pixmap,
            "mode": self._mode,
            "grid_info": self._grid_info,
            "current_tile": self._current_tile,
            "show_grid": self._show_grid,
            "show_crosshair": self._show_crosshair,
            "zoom_factor": self._zoom_factor,
            "pan_offset": self._pan_offset,
        }

    def handle_wheel(self, event: QtGui.QWheelEvent):
        """Handle zoom via mouse wheel."""
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom_factor *= 1.15
        else:
            self._zoom_factor /= 1.15
        self._zoom_factor = max(0.1, min(10.0, self._zoom_factor))
        self._zoom_label.setText(f"{self._zoom_factor * 100:.0f}%")
        self._canvas_widget.update()

    def handle_mouse_press(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._last_mouse_pos = event.pos()

    def handle_mouse_move(self, event: QtGui.QMouseEvent):
        if self._is_panning and self._last_mouse_pos is not None:
            delta = event.pos() - self._last_mouse_pos
            self._pan_offset += QtCore.QPointF(delta.x(), delta.y())
            self._last_mouse_pos = event.pos()
            self._canvas_widget.update()

    def handle_mouse_release(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self._last_mouse_pos = None


class _CanvasArea(QtWidgets.QWidget):
    """
    Internal widget for rendering the preview image.
    Delegates state to the parent PreviewWidget.
    """

    def __init__(self, preview: PreviewWidget):
        super().__init__(preview)
        self._preview = preview
        self.setMouseTracking(True)

    def paintEvent(self, event):
        params = self._preview.get_paint_params()
        pixmap = params["pixmap"]

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)

        if pixmap is None:
            # Draw placeholder
            painter.fillRect(self.rect(), QtGui.QColor(40, 40, 40))
            painter.setPen(QtGui.QColor(120, 120, 120))
            if params["mode"] == "live":
                placeholder_text = "No camera feed — connect camera to start live view"
            else:
                placeholder_text = "No preview available"
            painter.drawText(
                self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, placeholder_text
            )
            painter.end()
            return

        # Compute scaled rect preserving aspect ratio
        zoom = params["zoom_factor"]
        pan = params["pan_offset"]
        widget_w = self.width()
        widget_h = self.height()
        img_w = pixmap.width()
        img_h = pixmap.height()

        # Base scale: fit image to widget
        base_scale = min(widget_w / img_w, widget_h / img_h)
        scale = base_scale * zoom

        scaled_w = img_w * scale
        scaled_h = img_h * scale

        # Center the image
        x = (widget_w - scaled_w) / 2 + pan.x()
        y = (widget_h - scaled_h) / 2 + pan.y()

        target_rect = QtCore.QRectF(x, y, scaled_w, scaled_h)

        # Draw background
        painter.fillRect(self.rect(), QtGui.QColor(30, 30, 30))

        # Draw image
        painter.drawPixmap(target_rect, pixmap, QtCore.QRectF(pixmap.rect()))

        # Mode-specific overlays
        if params["mode"] == "live":
            # Crosshair overlay
            if params["show_crosshair"]:
                self._draw_crosshair(painter, target_rect)
        else:
            # Grid overlay (composite mode)
            if params["show_grid"] and params["grid_info"]:
                self._draw_grid(
                    painter, target_rect, params["grid_info"], params["current_tile"]
                )

        painter.end()

    def _draw_crosshair(self, painter: QtGui.QPainter, target_rect: QtCore.QRectF):
        """Draw a centered crosshair reticle over the live image."""
        cx = target_rect.center().x()
        cy = target_rect.center().y()

        # Semi-transparent red crosshair lines across the full image
        pen = QtGui.QPen(QtGui.QColor(255, 0, 0, 160))
        pen.setWidth(1)
        painter.setPen(pen)

        # Full horizontal line
        painter.drawLine(
            QtCore.QPointF(target_rect.left(), cy),
            QtCore.QPointF(target_rect.right(), cy),
        )
        # Full vertical line
        painter.drawLine(
            QtCore.QPointF(cx, target_rect.top()),
            QtCore.QPointF(cx, target_rect.bottom()),
        )

        # Center circle
        pen.setColor(QtGui.QColor(255, 0, 0, 220))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QtCore.QPointF(cx, cy), 15, 15)

    def _draw_grid(
        self,
        painter: QtGui.QPainter,
        target_rect: QtCore.QRectF,
        grid_info: dict,
        current_tile: Optional[tuple[int, int]],
    ):
        """Draw tile grid overlay on the preview."""
        rows = grid_info["rows"]
        cols = grid_info["cols"]

        if rows < 1 or cols < 1:
            return

        cell_w = target_rect.width() / cols
        cell_h = target_rect.height() / rows

        # Grid lines
        pen = QtGui.QPen(QtGui.QColor(100, 200, 255, 80))
        pen.setWidth(1)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)

        # Vertical lines
        for c in range(1, cols):
            x = target_rect.x() + c * cell_w
            painter.drawLine(
                QtCore.QPointF(x, target_rect.top()),
                QtCore.QPointF(x, target_rect.bottom()),
            )

        # Horizontal lines
        for r in range(1, rows):
            y = target_rect.y() + r * cell_h
            painter.drawLine(
                QtCore.QPointF(target_rect.left(), y),
                QtCore.QPointF(target_rect.right(), y),
            )

        # Highlight current tile
        if current_tile is not None:
            r, c = current_tile
            if 0 <= r < rows and 0 <= c < cols:
                highlight_rect = QtCore.QRectF(
                    target_rect.x() + c * cell_w,
                    target_rect.y() + r * cell_h,
                    cell_w,
                    cell_h,
                )
                pen = QtGui.QPen(QtGui.QColor(255, 200, 0, 200))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(QtGui.QColor(255, 200, 0, 30))
                painter.drawRect(highlight_rect)

    def wheelEvent(self, event):
        self._preview.handle_wheel(event)

    def mousePressEvent(self, event):
        self._preview.handle_mouse_press(event)

    def mouseMoveEvent(self, event):
        self._preview.handle_mouse_move(event)

    def mouseReleaseEvent(self, event):
        self._preview.handle_mouse_release(event)
