"""Stitch stage: manual parameter panel + background stitching + zoomable preview."""

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from Image_Stitching.core.stitcher import stitch, StitchError
from Image_Stitching.core.exporter import export_image, ExportError
from Image_Stitching.core.models import StitchConfig, StitchOutput

from ...i18n import tr, language_manager

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Zoomable image view
# ------------------------------------------------------------------ #

class ZoomableImageView(QtWidgets.QGraphicsView):
    """QGraphicsView that supports mouse-wheel zoom and drag-to-pan.

    Usage
    -----
    - Scroll wheel          : zoom in / out (anchored at cursor)
    - Left-button drag      : pan
    - fit_view()            : zoom to fit the image in the viewport
    - zoom_to(factor)       : set absolute zoom (1.0 = 100 %)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        scene = QtWidgets.QGraphicsScene(self)
        self.setScene(scene)
        self._pix_item = scene.addPixmap(QtGui.QPixmap())

        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#1e1e1e")))
        self.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.setMinimumHeight(300)

        self._placeholder = ""

    # ---------------------------------------------------------------- #
    #  Public API
    # ---------------------------------------------------------------- #

    def set_image(self, image_bgr: np.ndarray):
        """Display a BGR numpy image and fit it in the view."""
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QtGui.QImage(
            rgb.data, w, h, rgb.strides[0], QtGui.QImage.Format.Format_RGB888
        ).copy()
        pix = QtGui.QPixmap.fromImage(qimg)
        self._pix_item.setPixmap(pix)
        self.scene().setSceneRect(self._pix_item.boundingRect())
        self._placeholder = ""
        self.fit_view()

    def clear_image(self, placeholder: str = ""):
        """Remove the image and show a placeholder text."""
        self._placeholder = placeholder
        self._pix_item.setPixmap(QtGui.QPixmap())
        self.scene().setSceneRect(QtCore.QRectF(0, 0, 1, 1))
        self.viewport().update()

    def fit_view(self):
        """Scale the view so the image fills the viewport."""
        if not self._pix_item.pixmap().isNull():
            self.fitInView(
                self._pix_item,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            )

    def zoom_to(self, factor: float):
        """Set absolute zoom level (1.0 = 100 %)."""
        self.resetTransform()
        self.scale(factor, factor)

    def zoom_level(self) -> float:
        """Return the current horizontal scale factor."""
        return self.transform().m11()

    # ---------------------------------------------------------------- #
    #  Event overrides
    # ---------------------------------------------------------------- #

    def wheelEvent(self, event: QtGui.QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        current = self.transform().m11()
        new = current * factor
        if new < 0.02 or new > 200.0:
            return
        self.scale(factor, factor)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pix_item.pixmap().isNull() and self._placeholder:
            painter = QtGui.QPainter(self.viewport())
            painter.setPen(QtGui.QColor("#666"))
            painter.drawText(
                self.viewport().rect(),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                self._placeholder,
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep fit while image is first displayed (before user zooms)
        if not self._pix_item.pixmap().isNull():
            # Only auto-fit if user hasn't zoomed yet (scale close to fit scale)
            pass  # user controls zoom after first fit


# ------------------------------------------------------------------ #
#  Background worker
# ------------------------------------------------------------------ #

class StitchWorker(QtCore.QThread):
    """Runs stitch() in a background thread."""

    progress = QtCore.Signal(int, str)
    finished_ok = QtCore.Signal(object)  # StitchOutput
    error_occurred = QtCore.Signal(str)

    def __init__(self, config: StitchConfig, parent=None):
        super().__init__(parent)
        self._config = config

    def run(self):
        try:
            result = stitch(self._config, progress_callback=self._on_progress)
            self.finished_ok.emit(result)
        except (StitchError, Exception) as e:
            self.error_occurred.emit(str(e))

    def _on_progress(self, percent: int, message: str):
        self.progress.emit(percent, message)


# ------------------------------------------------------------------ #
#  Stage widget
# ------------------------------------------------------------------ #

class StitchStage(QtWidgets.QWidget):
    """Second stage: image stitching with manual parameter panel.

    The user sets parameters and clicks "Start Stitch" to begin.
    set_input_dir() only updates the displayed path without auto-starting.

    Signals
    -------
    stitch_exported(str)
        Emitted when the user exports the stitched panorama as PNG.
        Carries the output file path.
    """

    stitch_exported = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[StitchWorker] = None
        self._result: Optional[StitchOutput] = None
        self._input_dir: Optional[Path] = None
        self._input_files: Optional[list[Path]] = None
        self._setup_ui()
        language_manager().language_changed.connect(self._retranslate_ui)

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Input selection row ---
        dir_row = QtWidgets.QHBoxLayout()
        self._dir_key_label = QtWidgets.QLabel()
        self._dir_key_label.setStyleSheet("font-weight: bold;")
        dir_row.addWidget(self._dir_key_label)
        self._dir_val_label = QtWidgets.QLabel("—")
        self._dir_val_label.setStyleSheet("color: #aaa;")
        self._dir_val_label.setMinimumWidth(80)
        dir_row.addWidget(self._dir_val_label, stretch=1)
        self._browse_dir_btn = QtWidgets.QPushButton()
        self._browse_dir_btn.setFixedHeight(26)
        self._browse_dir_btn.clicked.connect(self._on_browse_dir)
        dir_row.addWidget(self._browse_dir_btn)
        self._select_files_btn = QtWidgets.QPushButton()
        self._select_files_btn.setFixedHeight(26)
        self._select_files_btn.clicked.connect(self._on_select_files)
        dir_row.addWidget(self._select_files_btn)
        layout.addLayout(dir_row)

        # --- Parameters group box ---
        self._params_group = QtWidgets.QGroupBox()
        params_layout = QtWidgets.QFormLayout(self._params_group)
        params_layout.setSpacing(6)

        # Overlap X
        self._overlap_x_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._overlap_x_slider.setRange(0, 70)
        self._overlap_x_slider.setValue(20)
        self._overlap_x_label = QtWidgets.QLabel("20%")
        self._overlap_x_label.setFixedWidth(40)
        self._overlap_x_slider.valueChanged.connect(
            lambda v: self._overlap_x_label.setText(f"{v}%")
        )
        overlap_x_row = QtWidgets.QHBoxLayout()
        overlap_x_row.addWidget(self._overlap_x_slider)
        overlap_x_row.addWidget(self._overlap_x_label)
        self._overlap_x_form_label = QtWidgets.QLabel()
        params_layout.addRow(self._overlap_x_form_label, overlap_x_row)

        # Overlap Y
        self._overlap_y_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._overlap_y_slider.setRange(0,70)
        self._overlap_y_slider.setValue(20)
        self._overlap_y_label = QtWidgets.QLabel("20%")
        self._overlap_y_label.setFixedWidth(40)
        self._overlap_y_slider.valueChanged.connect(
            lambda v: self._overlap_y_label.setText(f"{v}%")
        )
        overlap_y_row = QtWidgets.QHBoxLayout()
        overlap_y_row.addWidget(self._overlap_y_slider)
        overlap_y_row.addWidget(self._overlap_y_label)
        self._overlap_y_form_label = QtWidgets.QLabel()
        params_layout.addRow(self._overlap_y_form_label, overlap_y_row)

        # Resolution mode
        self._resolution_combo = QtWidgets.QComboBox()
        self._resolution_form_label = QtWidgets.QLabel()
        params_layout.addRow(self._resolution_form_label, self._resolution_combo)

        # Exposure normalization
        self._exposure_check = QtWidgets.QCheckBox()
        self._exposure_check.setChecked(True)
        self._exposure_form_label = QtWidgets.QLabel()
        params_layout.addRow(self._exposure_form_label, self._exposure_check)

        # Auto-align + range
        align_row = QtWidgets.QHBoxLayout()
        self._align_check = QtWidgets.QCheckBox()
        self._align_check.setChecked(False)
        align_row.addWidget(self._align_check)
        self._align_range_spin = QtWidgets.QSpinBox()
        self._align_range_spin.setRange(1, 200)
        self._align_range_spin.setValue(20)
        self._align_range_spin.setFixedWidth(60)
        align_row.addWidget(self._align_range_spin)
        self._align_px_label = QtWidgets.QLabel()
        align_row.addWidget(self._align_px_label)
        align_row.addStretch()
        self._align_form_label = QtWidgets.QLabel()
        params_layout.addRow(self._align_form_label, align_row)

        layout.addWidget(self._params_group)

        # --- Start Stitch button ---
        self._start_btn = QtWidgets.QPushButton()
        self._start_btn.setMinimumHeight(38)
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #2a82da; color: white; "
            "font-weight: bold; padding: 6px 20px; }"
            "QPushButton:hover { background-color: #3a92ea; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self._start_btn.clicked.connect(self._on_start_stitch)
        layout.addWidget(self._start_btn)

        # --- Progress ---
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setMinimumHeight(22)
        layout.addWidget(self._progress_bar)

        self._status_label = QtWidgets.QLabel()
        layout.addWidget(self._status_label)

        # --- Image view toolbar ---
        view_toolbar = QtWidgets.QHBoxLayout()
        self._fit_btn = QtWidgets.QPushButton()
        self._fit_btn.setFixedHeight(24)
        self._fit_btn.setFixedWidth(80)
        self._fit_btn.clicked.connect(self._on_fit)
        view_toolbar.addWidget(self._fit_btn)
        self._zoom_100_btn = QtWidgets.QPushButton()
        self._zoom_100_btn.setFixedHeight(24)
        self._zoom_100_btn.setFixedWidth(50)
        self._zoom_100_btn.clicked.connect(self._on_zoom_100)
        view_toolbar.addWidget(self._zoom_100_btn)
        self._zoom_label = QtWidgets.QLabel("—")
        self._zoom_label.setStyleSheet("color: #888; font-size: 11px;")
        view_toolbar.addWidget(self._zoom_label)
        view_toolbar.addStretch()
        layout.addLayout(view_toolbar)

        # --- Zoomable preview ---
        self._image_view = ZoomableImageView()
        self._image_view.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        # Intercept wheel to update zoom label
        self._image_view.wheelEvent = self._on_view_wheel
        layout.addWidget(self._image_view, stretch=1)

        # --- Export button ---
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self._export_btn = QtWidgets.QPushButton()
        self._export_btn.setMinimumWidth(120)
        self._export_btn.setMinimumHeight(36)
        self._export_btn.setStyleSheet(
            "QPushButton { background-color: #1a6b1a; color: white; "
            "font-weight: bold; padding: 6px 20px; }"
            "QPushButton:hover { background-color: #228b22; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._retranslate_ui()

    # ------------------------------------------------------------------ #
    #  Zoom toolbar helpers
    # ------------------------------------------------------------------ #

    def _on_fit(self):
        self._image_view.fit_view()
        self._update_zoom_label()

    def _on_zoom_100(self):
        self._image_view.zoom_to(1.0)
        self._update_zoom_label()

    def _on_view_wheel(self, event: QtGui.QWheelEvent):
        ZoomableImageView.wheelEvent(self._image_view, event)
        self._update_zoom_label()

    def _update_zoom_label(self):
        pct = int(self._image_view.zoom_level() * 100)
        self._zoom_label.setText(f"{pct} %")

    # ------------------------------------------------------------------ #
    #  Translations
    # ------------------------------------------------------------------ #

    @QtCore.Slot()
    def _retranslate_ui(self):
        self._dir_key_label.setText(tr("stitch.input_dir"))
        self._browse_dir_btn.setText(tr("stitch.browse_dir"))
        self._select_files_btn.setText(tr("stitch.select_files"))
        self._params_group.setTitle(tr("stitch.params_group"))
        self._overlap_x_form_label.setText(tr("stitch.overlap_x"))
        self._overlap_y_form_label.setText(tr("stitch.overlap_y"))
        self._resolution_form_label.setText(tr("stitch.resolution"))
        self._exposure_form_label.setText(tr("stitch.exposure"))
        self._align_form_label.setText(tr("stitch.align"))
        self._align_px_label.setText(tr("stitch.px"))
        self._fit_btn.setText(tr("stitch.zoom_fit"))
        self._zoom_100_btn.setText(tr("stitch.zoom_100"))
        self._start_btn.setText(tr("stitch.start_btn"))
        self._export_btn.setText(tr("stitch.export_btn"))

        current_idx = self._resolution_combo.currentIndex()
        self._resolution_combo.blockSignals(True)
        self._resolution_combo.clear()
        self._resolution_combo.addItems([
            tr("stitch.res_resize"),
            tr("stitch.res_pad"),
            tr("stitch.res_strict"),
        ])
        self._resolution_combo.setCurrentIndex(max(0, current_idx))
        self._resolution_combo.blockSignals(False)

        if not self._status_label.text() or self._status_label.text() in (
            "Ready", "就绪", "Listo"
        ):
            self._status_label.setText(tr("stitch.ready"))

        if self._result is None:
            placeholder = (
                tr("stitch.waiting") if self._input_dir is None
                else tr("stitch.preview_placeholder")
            )
            self._image_view.clear_image(placeholder)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def set_input_dir(self, path: Path):
        """Set the input directory. Does NOT auto-start stitching."""
        self._input_dir = path
        self._input_files = None
        self._dir_val_label.setText(str(path))
        self._dir_val_label.setStyleSheet("color: #eee;")
        if self._result is None:
            self._image_view.clear_image(tr("stitch.preview_placeholder"))
            self._status_label.setText(tr("stitch.ready"))

    # ------------------------------------------------------------------ #
    #  Manual input selection
    # ------------------------------------------------------------------ #

    @QtCore.Slot()
    def _on_browse_dir(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, tr("stitch.browse_dir"),
            str(self._input_dir) if self._input_dir else "",
        )
        if folder:
            self.set_input_dir(Path(folder))

    @QtCore.Slot()
    def _on_select_files(self):
        start_dir = str(self._input_dir) if self._input_dir else ""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, tr("stitch.select_files"), start_dir,
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp);;All files (*)",
        )
        if not paths:
            return
        self._input_files = [Path(p) for p in paths]
        self._input_dir = self._input_files[0].parent
        self._dir_val_label.setText(
            tr("stitch.files_selected").format(len(self._input_files))
        )
        self._dir_val_label.setStyleSheet("color: #eee;")
        if self._result is None:
            self._image_view.clear_image(tr("stitch.preview_placeholder"))
            self._status_label.setText(tr("stitch.ready"))

    # ------------------------------------------------------------------ #
    #  Stitching
    # ------------------------------------------------------------------ #

    @QtCore.Slot()
    def _on_start_stitch(self):
        if self._input_dir is None and self._input_files is None:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self._result = None
        self._export_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._status_label.setText(tr("stitch.stitching"))
        self._image_view.clear_image(tr("stitch.stitching"))

        overlap_x = self._overlap_x_slider.value() / 100.0
        overlap_y = self._overlap_y_slider.value() / 100.0

        res_map = {0: "resize_to_first", 1: "pad_to_first", 2: "strict"}
        resolution_mode = res_map.get(self._resolution_combo.currentIndex(), "resize_to_first")

        enable_exposure = self._exposure_check.isChecked()
        enable_align = self._align_check.isChecked()
        align_range = self._align_range_spin.value() if enable_align else 20

        if self._input_files is not None:
            config = StitchConfig(
                input_dir=None,
                input_paths=self._input_files,
                overlap_x=overlap_x,
                overlap_y=overlap_y,
                resolution_mode=resolution_mode,
                enable_exposure=enable_exposure,
                enable_align=enable_align,
                max_align_shift=align_range,
            )
        else:
            config = StitchConfig(
                input_dir=self._input_dir,
                overlap_x=overlap_x,
                overlap_y=overlap_y,
                resolution_mode=resolution_mode,
                enable_exposure=enable_exposure,
                enable_align=enable_align,
                max_align_shift=align_range,
            )

        self._worker = StitchWorker(config, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_stitch_done)
        self._worker.error_occurred.connect(self._on_stitch_error)
        self._worker.start()

    @QtCore.Slot(int, str)
    def _on_progress(self, percent: int, message: str):
        self._progress_bar.setValue(percent)
        self._status_label.setText(message)

    @QtCore.Slot(object)
    def _on_stitch_done(self, result: StitchOutput):
        self._result = result
        self._worker = None
        self._progress_bar.setValue(100)
        self._status_label.setText(
            tr("stitch.done").format(
                result.rows, result.cols,
                result.tile_width, result.tile_height,
                result.source_size_summary,
            )
        )
        self._export_btn.setEnabled(True)
        self._image_view.set_image(result.preview)
        self._update_zoom_label()
        self._dir_val_label.setText(tr("stitch.complete_hint"))

    @QtCore.Slot(str)
    def _on_stitch_error(self, msg: str):
        self._worker = None
        self._progress_bar.setValue(0)
        self._status_label.setText(tr("stitch.failed").format(msg))
        self._image_view.clear_image(tr("stitch.failed").format(msg))
        QtWidgets.QMessageBox.critical(self, tr("stitch.error_title"), msg)

    # ------------------------------------------------------------------ #
    #  Export
    # ------------------------------------------------------------------ #

    def _on_export(self):
        if self._result is None:
            return

        default_name = "stitched_output.png"
        if self._input_dir is not None:
            default_name = str(self._input_dir.parent / "stitched_output.png")

        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            tr("stitch.export_title"),
            default_name,
            "PNG (*.png);;TIFF (*.tif *.tiff)",
        )
        if not output_path:
            return

        self._status_label.setText(tr("stitch.exporting"))
        QtWidgets.QApplication.processEvents()
        try:
            export_image(Path(output_path), self._result.image)
            self._status_label.setText(tr("stitch.export_ok").format(output_path))
            self.stitch_exported.emit(output_path)
        except ExportError as e:
            self._status_label.setText(tr("stitch.export_failed"))
            QtWidgets.QMessageBox.critical(self, tr("stitch.export_error_title"), str(e))
