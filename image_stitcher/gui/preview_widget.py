"""
Live camera preview widget.

Displays a real-time camera feed with optional crosshair overlay.
Used during S-pattern scanning to let the user verify image clarity
before confirming capture at each position.
"""

import logging
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)


class PreviewWidget(QtWidgets.QWidget):
    """
    Widget that displays a live camera feed.

    Features:
    - Real-time camera frame display
    - Auto-scaling to fit the widget while preserving aspect ratio
    - Crosshair overlay for alignment
    - Current position info display
    - Mouse-wheel zoom and pan (middle-click drag)
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._pixmap: Optional[QtGui.QPixmap] = None
        self._show_crosshair = True
        self._auto_level = True
        self._zoom_factor = 1.0
        self._pan_offset = QtCore.QPointF(0, 0)
        self._last_mouse_pos: Optional[QtCore.QPoint] = None
        self._is_panning = False
        self._position_text = ""

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

        # Crosshair toggle
        self._crosshair_checkbox = QtWidgets.QCheckBox("Crosshair")
        self._crosshair_checkbox.setChecked(True)
        self._crosshair_checkbox.toggled.connect(self._on_crosshair_toggled)
        toolbar.addWidget(self._crosshair_checkbox)

        self._auto_level_checkbox = QtWidgets.QCheckBox("Auto Level")
        self._auto_level_checkbox.setChecked(True)
        self._auto_level_checkbox.toggled.connect(self._on_auto_level_toggled)
        toolbar.addWidget(self._auto_level_checkbox)

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
        if self._auto_level:
            display = self._to_uint8_auto_level(frame)
        elif frame.dtype == np.uint16:
            # Fixed linear mapping for Mono14 in uint16 container.
            display_f32 = frame.astype(np.float32) * (255.0 / 16383.0)
            display_f32 *= 4.0
            display = np.clip(display_f32, 0.0, 255.0).astype(np.uint8)
        elif frame.dtype == np.uint8:
            display = frame
        else:
            # Normalize to uint8
            fmin = float(frame.min())
            fmax = float(frame.max())
            if fmax > fmin:
                display = ((frame - fmin) / (fmax - fmin) * 255).astype(np.uint8)
            else:
                display = np.zeros(frame.shape[:2], dtype=np.uint8)

        if display.ndim < 2:
            return

        h = int(display.shape[0])
        w = int(display.shape[1])
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

    def set_position_text(self, text: str):
        """
        Set position text to display as overlay.

        Parameters
        ----------
        text : str
            Position information string, e.g. "Position (1,2) - 1500.0, 2000.0 um"
        """
        self._position_text = text
        self._canvas_widget.update()

    def clear(self):
        """Clear the preview."""
        self._pixmap = None
        self._position_text = ""
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

    def _on_auto_level_toggled(self, checked: bool):
        self._auto_level = checked

    @staticmethod
    def _to_uint8_auto_level(frame: np.ndarray) -> np.ndarray:
        """Convert frame to uint8 using robust percentile stretch."""
        if frame.dtype == np.uint8:
            f32 = frame.astype(np.float32)
        else:
            f32 = frame.astype(np.float32, copy=False)

        lo = float(np.percentile(f32, 1.0))
        hi = float(np.percentile(f32, 99.0))

        if hi <= lo:
            return np.zeros(frame.shape[:2], dtype=np.uint8)

        stretched = np.clip((f32 - lo) * (255.0 / (hi - lo)), 0.0, 255.0)
        return stretched.astype(np.uint8)

    def _fit_to_view(self):
        self._zoom_factor = 1.0
        self._pan_offset = QtCore.QPointF(0, 0)
        self._zoom_label.setText("100%")
        self._canvas_widget.update()

    def get_paint_params(self):
        """Return current state for painting by _CanvasArea."""
        return {
            "pixmap": self._pixmap,
            "show_crosshair": self._show_crosshair,
            "zoom_factor": self._zoom_factor,
            "pan_offset": self._pan_offset,
            "position_text": self._position_text,
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
            placeholder_text = "No camera feed — connect camera to start live view"
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

        # Crosshair overlay
        if params["show_crosshair"]:
            self._draw_crosshair(painter, target_rect)

        # Position text overlay
        if params["position_text"]:
            self._draw_position_text(painter, params["position_text"])

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

    def _draw_position_text(self, painter: QtGui.QPainter, text: str):
        """Draw position information text at the top of the widget."""
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)

        # Background rect for readability
        metrics = QtGui.QFontMetrics(font)
        text_rect = metrics.boundingRect(text)
        bg_rect = QtCore.QRectF(10, 10, text_rect.width() + 20, text_rect.height() + 10)
        painter.fillRect(bg_rect, QtGui.QColor(0, 0, 0, 160))

        # Text
        painter.setPen(QtGui.QColor(255, 255, 0, 230))
        painter.drawText(
            QtCore.QRectF(20, 12, text_rect.width() + 10, text_rect.height() + 10),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def wheelEvent(self, event):
        self._preview.handle_wheel(event)

    def mousePressEvent(self, event):
        self._preview.handle_mouse_press(event)

    def mouseMoveEvent(self, event):
        self._preview.handle_mouse_move(event)

    def mouseReleaseEvent(self, event):
        self._preview.handle_mouse_release(event)
