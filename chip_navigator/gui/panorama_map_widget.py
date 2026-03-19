"""
Panorama map widget — displays a chip panorama image with interactive
point selection, zoom/pan, rotation, and overlay annotations.

Features
--------
- Load any image file (PNG, TIFF, BMP, JPEG)
- Mouse-wheel zoom + middle-click pan (consistent with PreviewWidget)
- 90-degree step rotation (0 / 90 / 180 / 270)
- Left-click emits pixel coordinates for calibration or navigation
  (always in *original* image coordinates, regardless of rotation)
- Draw calibration reference points (green), target point (red),
  and current stage position (blue) as overlays
- Coordinate readout on mouse hover

Rotation model
--------------
Internally we store ``_rotation_steps`` (0–3) representing multiples
of 90° clockwise.  The displayed image is a *view-only* rotation;
all external coordinates (``point_clicked`` signal, calibration points,
overlay positions) are always in the **original image** coordinate
system.  Coordinate conversions between the original and rotated
frames use discrete 90° formulae — no floating-point trigonometry.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)


class PanoramaMapWidget(QtWidgets.QWidget):
    """
    Interactive panorama image viewer with point selection.

    Signals
    -------
    point_clicked(float, float)
        Emitted when the user left-clicks on the image.
        Values are pixel coordinates (u, v) in **original** image space.
    rotation_changed(int)
        Emitted when the rotation angle changes.  Value is degrees
        (0, 90, 180, 270).
    """

    point_clicked = QtCore.Signal(float, float)
    rotation_changed = QtCore.Signal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._pixmap: Optional[QtGui.QPixmap] = None
        self._image_path: str = ""

        # View transform state
        self._zoom_factor: float = 1.0
        self._pan_offset = QtCore.QPointF(0, 0)
        self._is_panning: bool = False
        self._last_mouse_pos: Optional[QtCore.QPoint] = None

        # Rotation: 0 = 0°, 1 = 90° CW, 2 = 180°, 3 = 270° CW
        self._rotation_steps: int = 0

        # Overlay points (always in original image coords)
        self._calibration_points: List[Tuple[float, float]] = []
        self._target_point: Optional[Tuple[float, float]] = None
        self._stage_position_pixel: Optional[Tuple[float, float]] = None

        # Coordinate display
        self._hover_pixel: Optional[Tuple[float, float]] = None

        self._setup_ui()

        self.setMinimumSize(400, 300)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()

        self._load_btn = QtWidgets.QPushButton("Load Image")
        self._load_btn.setMaximumWidth(100)
        self._load_btn.clicked.connect(self._on_load_image)
        toolbar.addWidget(self._load_btn)

        self._fit_btn = QtWidgets.QPushButton("Fit")
        self._fit_btn.setMaximumWidth(50)
        self._fit_btn.clicked.connect(self._fit_to_view)
        toolbar.addWidget(self._fit_btn)

        self._zoom_label = QtWidgets.QLabel("100%")
        self._zoom_label.setMinimumWidth(50)
        toolbar.addWidget(self._zoom_label)

        toolbar.addSpacing(12)

        # Rotation buttons
        self._rot_left_btn = QtWidgets.QPushButton("↶ 90°")
        self._rot_left_btn.setToolTip("Rotate left 90° (counter-clockwise)")
        self._rot_left_btn.setMaximumWidth(60)
        self._rot_left_btn.clicked.connect(self.rotate_left_90)
        toolbar.addWidget(self._rot_left_btn)

        self._rot_right_btn = QtWidgets.QPushButton("↷ 90°")
        self._rot_right_btn.setToolTip("Rotate right 90° (clockwise)")
        self._rot_right_btn.setMaximumWidth(60)
        self._rot_right_btn.clicked.connect(self.rotate_right_90)
        toolbar.addWidget(self._rot_right_btn)

        self._rotation_label = QtWidgets.QLabel("0°")
        self._rotation_label.setMinimumWidth(30)
        self._rotation_label.setStyleSheet("font-weight: bold;")
        toolbar.addWidget(self._rotation_label)

        toolbar.addStretch()

        self._coord_label = QtWidgets.QLabel("")
        toolbar.addWidget(self._coord_label)

        self._info_label = QtWidgets.QLabel("No image loaded")
        toolbar.addWidget(self._info_label)

        layout.addLayout(toolbar)

        # Canvas
        self._canvas = _PanoramaCanvas(self)
        layout.addWidget(self._canvas, stretch=1)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def load_image(self, filepath: str) -> bool:
        """
        Load a panorama image from file.

        Returns True on success, False on failure.
        """
        filepath = str(filepath)
        pixmap = QtGui.QPixmap(filepath)
        if pixmap.isNull():
            logger.error(f"Failed to load image: {filepath}")
            return False

        self._pixmap = pixmap
        self._image_path = filepath
        self._fit_to_view()
        self._info_label.setText(
            f"{Path(filepath).name}  ({pixmap.width()} x {pixmap.height()})"
        )
        logger.info(f"Panorama loaded: {filepath} ({pixmap.width()}x{pixmap.height()})")
        return True

    @property
    def has_image(self) -> bool:
        return self._pixmap is not None

    @property
    def image_path(self) -> str:
        return self._image_path

    def set_calibration_points(self, points: List[Tuple[float, float]]) -> None:
        """Set the list of calibration reference points (original pixel coords)."""
        self._calibration_points = list(points)
        self._canvas.update()

    def set_target_point(self, point: Optional[Tuple[float, float]]) -> None:
        """Set or clear the navigation target point (original pixel coords)."""
        self._target_point = point
        self._canvas.update()

    def set_stage_position(self, point: Optional[Tuple[float, float]]) -> None:
        """
        Set or clear the current stage position in original pixel coords.

        This is computed by the main window using the inverse affine
        transform from the calibration.
        """
        self._stage_position_pixel = point
        self._canvas.update()

    def clear_overlays(self) -> None:
        """Clear all overlay points."""
        self._calibration_points.clear()
        self._target_point = None
        self._stage_position_pixel = None
        self._canvas.update()

    # ------------------------------------------------------------------ #
    #  Rotation
    # ------------------------------------------------------------------ #

    @property
    def rotation_degrees(self) -> int:
        """Current rotation angle in degrees (0, 90, 180, 270)."""
        return self._rotation_steps * 90

    def rotate_right_90(self) -> None:
        """Rotate the view 90° clockwise."""
        self._rotation_steps = (self._rotation_steps + 1) % 4
        self._on_rotation_changed()

    def rotate_left_90(self) -> None:
        """Rotate the view 90° counter-clockwise."""
        self._rotation_steps = (self._rotation_steps - 1) % 4
        self._on_rotation_changed()

    def reset_rotation(self) -> None:
        """Reset rotation to 0°."""
        self._rotation_steps = 0
        self._on_rotation_changed()

    def _on_rotation_changed(self) -> None:
        deg = self.rotation_degrees
        self._rotation_label.setText(f"{deg}°")
        self._pan_offset = QtCore.QPointF(0, 0)  # reset pan on rotation
        self._canvas.update()
        self.rotation_changed.emit(deg)
        logger.info(f"Panorama rotation set to {deg}°")

    # ------------------------------------------------------------------ #
    #  Rotated image dimensions
    # ------------------------------------------------------------------ #

    def _rotated_size(self) -> Tuple[int, int]:
        """
        Return (width, height) of the image as displayed after rotation.

        For 0°/180° the dimensions are unchanged; for 90°/270° they swap.
        """
        if self._pixmap is None:
            return (0, 0)
        w, h = self._pixmap.width(), self._pixmap.height()
        if self._rotation_steps % 2 == 0:
            return (w, h)
        else:
            return (h, w)

    # ------------------------------------------------------------------ #
    #  Coordinate transforms: original <-> rotated image coords
    # ------------------------------------------------------------------ #

    def _original_to_rotated(self, u: float, v: float) -> Tuple[float, float]:
        """
        Convert original image pixel (u, v) to rotated display coords.

        Uses discrete 90° formulae:
          0°:   (u, v)            ->  (u, v)
          90°:  (u, v) CW         ->  (H-1-v, u)
          180°: (u, v)            ->  (W-1-u, H-1-v)
          270°: (u, v) CW (=90°CCW) -> (v, W-1-u)

        W, H are the *original* image width and height.
        """
        if self._pixmap is None:
            return (u, v)
        W = self._pixmap.width()
        H = self._pixmap.height()
        s = self._rotation_steps
        if s == 0:
            return (u, v)
        elif s == 1:  # 90° CW
            return (H - 1 - v, u)
        elif s == 2:  # 180°
            return (W - 1 - u, H - 1 - v)
        else:  # 270° CW
            return (v, W - 1 - u)

    def _rotated_to_original(self, ru: float, rv: float) -> Tuple[float, float]:
        """
        Convert rotated display coords back to original image pixel (u, v).

        Inverse of ``_original_to_rotated``.
        """
        if self._pixmap is None:
            return (ru, rv)
        W = self._pixmap.width()
        H = self._pixmap.height()
        s = self._rotation_steps
        if s == 0:
            return (ru, rv)
        elif s == 1:  # inverse of 90° CW
            return (rv, H - 1 - ru)
        elif s == 2:  # inverse of 180°
            return (W - 1 - ru, H - 1 - rv)
        else:  # inverse of 270° CW
            return (W - 1 - rv, ru)

    # ------------------------------------------------------------------ #
    #  View control
    # ------------------------------------------------------------------ #

    def _fit_to_view(self) -> None:
        self._zoom_factor = 1.0
        self._pan_offset = QtCore.QPointF(0, 0)
        self._zoom_label.setText("100%")
        self._canvas.update()

    def _on_load_image(self) -> None:
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Panorama Image",
            "",
            "Images (*.png *.tif *.tiff *.bmp *.jpg *.jpeg);;All Files (*)",
        )
        if filepath:
            self.load_image(filepath)

    # ------------------------------------------------------------------ #
    #  Coordinate mapping: widget <-> rotated image pixel
    # ------------------------------------------------------------------ #

    def _get_image_rect(self) -> Optional[QtCore.QRectF]:
        """
        Compute the on-screen rectangle for the (rotated) image.
        """
        if self._pixmap is None:
            return None

        cw = self._canvas.width()
        ch = self._canvas.height()
        rw, rh = self._rotated_size()

        base_scale = min(cw / rw, ch / rh)
        scale = base_scale * self._zoom_factor
        sw = rw * scale
        sh = rh * scale

        x = (cw - sw) / 2 + self._pan_offset.x()
        y = (ch - sh) / 2 + self._pan_offset.y()

        return QtCore.QRectF(x, y, sw, sh)

    def _widget_to_rotated(
        self, widget_pos: QtCore.QPointF
    ) -> Optional[Tuple[float, float]]:
        """Convert widget coordinates to rotated image pixel coordinates."""
        rect = self._get_image_rect()
        if rect is None:
            return None

        rw, rh = self._rotated_size()
        ru = (widget_pos.x() - rect.x()) / rect.width() * rw
        rv = (widget_pos.y() - rect.y()) / rect.height() * rh

        if 0 <= ru <= rw and 0 <= rv <= rh:
            return (ru, rv)
        return None

    def _rotated_to_widget(self, ru: float, rv: float) -> Optional[QtCore.QPointF]:
        """Convert rotated image pixel coordinates to widget coordinates."""
        rect = self._get_image_rect()
        if rect is None:
            return None

        rw, rh = self._rotated_size()
        wx = rect.x() + (ru / rw) * rect.width()
        wy = rect.y() + (rv / rh) * rect.height()
        return QtCore.QPointF(wx, wy)

    # -- Convenience: original image <-> widget (used by overlays) -----

    def _widget_to_image(
        self, widget_pos: QtCore.QPointF
    ) -> Optional[Tuple[float, float]]:
        """Convert widget coordinates to *original* image pixel coordinates."""
        rotated = self._widget_to_rotated(widget_pos)
        if rotated is None:
            return None
        return self._rotated_to_original(rotated[0], rotated[1])

    def _image_to_widget(self, u: float, v: float) -> Optional[QtCore.QPointF]:
        """Convert *original* image pixel coords to widget coordinates."""
        ru, rv = self._original_to_rotated(u, v)
        return self._rotated_to_widget(ru, rv)

    # ------------------------------------------------------------------ #
    #  Paint parameters (for canvas)
    # ------------------------------------------------------------------ #

    def get_paint_params(self) -> dict:
        return {
            "pixmap": self._pixmap,
            "zoom_factor": self._zoom_factor,
            "pan_offset": self._pan_offset,
            "rotation_steps": self._rotation_steps,
            "calibration_points": self._calibration_points,
            "target_point": self._target_point,
            "stage_position_pixel": self._stage_position_pixel,
        }

    # ------------------------------------------------------------------ #
    #  Event handlers (delegated from canvas)
    # ------------------------------------------------------------------ #

    def handle_wheel(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom_factor *= 1.15
        else:
            self._zoom_factor /= 1.15
        self._zoom_factor = max(0.05, min(20.0, self._zoom_factor))
        self._zoom_label.setText(f"{self._zoom_factor * 100:.0f}%")
        self._canvas.update()

    def handle_mouse_press(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._last_mouse_pos = event.pos()
        elif event.button() == QtCore.Qt.MouseButton.LeftButton:
            # Emit original image coordinates
            pos = self._widget_to_image(QtCore.QPointF(event.pos()))
            if pos is not None:
                self.point_clicked.emit(pos[0], pos[1])

    def handle_mouse_move(self, event: QtGui.QMouseEvent) -> None:
        if self._is_panning and self._last_mouse_pos is not None:
            delta = event.pos() - self._last_mouse_pos
            self._pan_offset += QtCore.QPointF(delta.x(), delta.y())
            self._last_mouse_pos = event.pos()
            self._canvas.update()

        # Update coordinate readout (show original image coords)
        pos = self._widget_to_image(QtCore.QPointF(event.pos()))
        if pos is not None:
            self._coord_label.setText(f"px: ({pos[0]:.0f}, {pos[1]:.0f})")
        else:
            self._coord_label.setText("")

    def handle_mouse_release(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self._last_mouse_pos = None


# ------------------------------------------------------------------ #
#  Canvas (internal rendering widget)
# ------------------------------------------------------------------ #


class _PanoramaCanvas(QtWidgets.QWidget):
    """Internal widget that renders the panorama image and overlays."""

    def __init__(self, parent: PanoramaMapWidget):
        super().__init__(parent)
        self._panorama = parent
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)

    def paintEvent(self, event):
        params = self._panorama.get_paint_params()
        pixmap = params["pixmap"]

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)

        if pixmap is None:
            painter.fillRect(self.rect(), QtGui.QColor(50, 50, 50))
            painter.setPen(QtGui.QColor(120, 120, 120))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                "No panorama image loaded\n\nClick 'Load Image' to open a chip photo",
            )
            painter.end()
            return

        # Draw background
        painter.fillRect(self.rect(), QtGui.QColor(30, 30, 30))

        # Compute image rect (for rotated dimensions)
        rect = self._panorama._get_image_rect()
        if rect is None:
            painter.end()
            return

        # Draw rotated image
        rotation_steps = params["rotation_steps"]
        self._draw_rotated_pixmap(painter, pixmap, rect, rotation_steps)

        # Draw overlays (all use original coords -> _image_to_widget)
        self._draw_calibration_points(painter, params)
        self._draw_stage_position(painter, params)
        self._draw_target_point(painter, params)

        painter.end()

    def _draw_rotated_pixmap(
        self,
        painter: QtGui.QPainter,
        pixmap: QtGui.QPixmap,
        rect: QtCore.QRectF,
        rotation_steps: int,
    ):
        """Draw the pixmap into *rect*, rotated by rotation_steps * 90°."""
        if rotation_steps == 0:
            painter.drawPixmap(rect, pixmap, QtCore.QRectF(pixmap.rect()))
            return

        # Use QTransform to rotate the pixmap before drawing
        transform = QtGui.QTransform()
        degrees = rotation_steps * 90

        # Rotate around pixmap center, then Qt gives us a new pixmap
        # with potentially swapped dimensions — we draw it into rect.
        rotated = pixmap.transformed(
            QtGui.QTransform().rotate(degrees),
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(rect, rotated, QtCore.QRectF(rotated.rect()))

    def _point_to_widget(self, u: float, v: float) -> Optional[QtCore.QPointF]:
        return self._panorama._image_to_widget(u, v)

    def _draw_calibration_points(self, painter: QtGui.QPainter, params: dict):
        """Draw green markers for calibration reference points."""
        points = params["calibration_points"]
        if not points:
            return

        for i, (u, v) in enumerate(points):
            wpt = self._point_to_widget(u, v)
            if wpt is None:
                continue

            # Green circle
            pen = QtGui.QPen(QtGui.QColor(0, 220, 0, 220))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(0, 220, 0, 60))
            painter.drawEllipse(wpt, 8, 8)

            # Cross
            painter.drawLine(
                QtCore.QPointF(wpt.x() - 12, wpt.y()),
                QtCore.QPointF(wpt.x() + 12, wpt.y()),
            )
            painter.drawLine(
                QtCore.QPointF(wpt.x(), wpt.y() - 12),
                QtCore.QPointF(wpt.x(), wpt.y() + 12),
            )

            # Label
            font = QtGui.QFont()
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QtGui.QColor(0, 255, 0, 255))
            painter.drawText(
                QtCore.QPointF(wpt.x() + 14, wpt.y() - 4),
                f"C{i + 1}",
            )

    def _draw_target_point(self, painter: QtGui.QPainter, params: dict):
        """Draw a red target crosshair for the navigation target."""
        target = params["target_point"]
        if target is None:
            return

        wpt = self._point_to_widget(target[0], target[1])
        if wpt is None:
            return

        # Red pulsing crosshair
        pen = QtGui.QPen(QtGui.QColor(255, 50, 50, 230))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        # Outer circle
        painter.drawEllipse(wpt, 14, 14)
        # Inner circle
        painter.drawEllipse(wpt, 4, 4)

        # Cross lines
        painter.drawLine(
            QtCore.QPointF(wpt.x() - 20, wpt.y()),
            QtCore.QPointF(wpt.x() - 6, wpt.y()),
        )
        painter.drawLine(
            QtCore.QPointF(wpt.x() + 6, wpt.y()),
            QtCore.QPointF(wpt.x() + 20, wpt.y()),
        )
        painter.drawLine(
            QtCore.QPointF(wpt.x(), wpt.y() - 20),
            QtCore.QPointF(wpt.x(), wpt.y() - 6),
        )
        painter.drawLine(
            QtCore.QPointF(wpt.x(), wpt.y() + 6),
            QtCore.QPointF(wpt.x(), wpt.y() + 20),
        )

        # Label
        font = QtGui.QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(255, 80, 80, 255))
        painter.drawText(
            QtCore.QPointF(wpt.x() + 18, wpt.y() - 6),
            "TARGET",
        )

    def _draw_stage_position(self, painter: QtGui.QPainter, params: dict):
        """Draw a blue marker for the current stage position."""
        pos = params["stage_position_pixel"]
        if pos is None:
            return

        wpt = self._point_to_widget(pos[0], pos[1])
        if wpt is None:
            return

        # Blue diamond
        pen = QtGui.QPen(QtGui.QColor(80, 150, 255, 230))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QtGui.QColor(80, 150, 255, 80))

        diamond = QtGui.QPolygonF(
            [
                QtCore.QPointF(wpt.x(), wpt.y() - 10),
                QtCore.QPointF(wpt.x() + 10, wpt.y()),
                QtCore.QPointF(wpt.x(), wpt.y() + 10),
                QtCore.QPointF(wpt.x() - 10, wpt.y()),
            ]
        )
        painter.drawPolygon(diamond)

        # Label
        font = QtGui.QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(100, 180, 255, 255))
        painter.drawText(
            QtCore.QPointF(wpt.x() + 14, wpt.y() + 4),
            "STAGE",
        )

    # ---- Event forwarding -------------------------------------------- #

    def wheelEvent(self, event):
        self._panorama.handle_wheel(event)

    def mousePressEvent(self, event):
        self._panorama.handle_mouse_press(event)

    def mouseMoveEvent(self, event):
        self._panorama.handle_mouse_move(event)

    def mouseReleaseEvent(self, event):
        self._panorama.handle_mouse_release(event)
