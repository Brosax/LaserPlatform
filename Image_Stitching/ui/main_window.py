from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.exporter import ExportError, export_image
from ..core.models import StitchConfig
from ..core.stitcher import StitchError, stitch


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("扫描图像拼接工具")
        self.resize(1200, 760)

        self._last_result = None
        self._selected_files: list[Path] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        controls = QVBoxLayout()
        controls.addWidget(self._build_input_group())
        controls.addWidget(self._build_param_group())
        controls.addWidget(self._build_grid_group())
        controls.addWidget(self._build_selection_group())
        controls.addWidget(self._build_actions_group())
        controls.addStretch(1)

        layout.addLayout(controls, 0)

        self.preview_label = QLabel("导入后点击“开始拼接”查看预览", self)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background: #f0f2f5; border: 1px solid #c8ccd0;")
        self.preview_label.setMinimumSize(700, 700)
        layout.addWidget(self.preview_label, 1)

    def _build_input_group(self) -> QGroupBox:
        box = QGroupBox("输入目录", self)
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.dir_edit = QLineEdit(self)
        self.dir_edit.setPlaceholderText("选择包含 11.png, 12.png ... 的目录")
        browse_btn = QPushButton("浏览", self)
        browse_btn.clicked.connect(self._choose_dir)
        choose_files_btn = QPushButton("选择图像", self)
        choose_files_btn.clicked.connect(self._choose_files)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(browse_btn)
        row.addWidget(choose_files_btn)

        form.addRow(row)
        return box

    def _build_grid_group(self) -> QGroupBox:
        box = QGroupBox("网格设置", self)
        form = QFormLayout(box)

        self.rows_spin = QSpinBox(self)
        self.rows_spin.setRange(0, 9)
        self.rows_spin.setValue(0)
        self.rows_spin.setSpecialValueText("自动")

        self.cols_spin = QSpinBox(self)
        self.cols_spin.setRange(0, 9)
        self.cols_spin.setValue(0)
        self.cols_spin.setSpecialValueText("自动")

        form.addRow("期望行数", self.rows_spin)
        form.addRow("期望列数", self.cols_spin)
        return box

    def _build_selection_group(self) -> QGroupBox:
        box = QGroupBox("已选图像", self)
        v = QVBoxLayout(box)
        self.file_list = QListWidget(self)
        self.file_list.setMinimumHeight(140)
        self.file_count_label = QLabel("当前: 使用目录扫描", self)
        v.addWidget(self.file_count_label)
        v.addWidget(self.file_list)
        return box

    def _build_param_group(self) -> QGroupBox:
        box = QGroupBox("拼接参数", self)
        form = QFormLayout(box)

        self.overlap_x_slider = QSlider(Qt.Horizontal, self)
        self.overlap_x_slider.setRange(0, 70)
        self.overlap_x_slider.setValue(20)
        self.overlap_x_label = QLabel("20%", self)
        self.overlap_x_slider.valueChanged.connect(
            lambda v: self.overlap_x_label.setText(f"{v}%")
        )

        self.overlap_y_slider = QSlider(Qt.Horizontal, self)
        self.overlap_y_slider.setRange(0, 70)
        self.overlap_y_slider.setValue(20)
        self.overlap_y_label = QLabel("20%", self)
        self.overlap_y_slider.valueChanged.connect(
            lambda v: self.overlap_y_label.setText(f"{v}%")
        )

        x_row = QHBoxLayout()
        x_row.addWidget(self.overlap_x_slider, 1)
        x_row.addWidget(self.overlap_x_label)
        y_row = QHBoxLayout()
        y_row.addWidget(self.overlap_y_slider, 1)
        y_row.addWidget(self.overlap_y_label)

        form.addRow("横向重叠", x_row)
        form.addRow("纵向重叠", y_row)

        self.resolution_mode_combo = QComboBox(self)
        self.resolution_mode_combo.addItem("统一到首张分辨率（推荐）", "resize_to_first")
        self.resolution_mode_combo.addItem("等比缩放并补边到首张", "pad_to_first")
        self.resolution_mode_combo.addItem("严格一致（不处理）", "strict")
        form.addRow("分辨率处理", self.resolution_mode_combo)

        self.exposure_cb = QCheckBox("亮度统一", self)
        self.exposure_cb.setChecked(True)
        self.align_cb = QCheckBox("自动微调对齐", self)
        self.align_cb.setChecked(False)

        align_shift_row = QHBoxLayout()
        self.align_shift_spin = QSpinBox(self)
        self.align_shift_spin.setRange(1, 80)
        self.align_shift_spin.setValue(20)
        align_shift_row.addWidget(self.align_shift_spin)
        align_shift_row.addWidget(QLabel("像素", self))

        form.addRow(self.exposure_cb)
        form.addRow(self.align_cb)
        form.addRow("微调范围", align_shift_row)
        return box

    def _build_actions_group(self) -> QGroupBox:
        box = QGroupBox("操作", self)
        v = QVBoxLayout(box)

        self.start_btn = QPushButton("开始拼接", self)
        self.start_btn.clicked.connect(self._start_stitch)

        self.export_btn = QPushButton("导出大图", self)
        self.export_btn.clicked.connect(self._export_image)
        self.export_btn.setEnabled(False)

        self.status_label = QLabel("就绪", self)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        v.addWidget(self.start_btn)
        v.addWidget(self.export_btn)
        v.addWidget(self.progress)
        v.addWidget(self.status_label)
        return box

    def _choose_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择图像目录")
        if selected:
            self.dir_edit.setText(selected)
            self._selected_files = []
            self._refresh_file_list()

    def _choose_files(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图像文件",
            "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if selected:
            self._selected_files = [Path(p) for p in selected]
            parent = self._selected_files[0].parent
            self.dir_edit.setText(str(parent))
            self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        if not self._selected_files:
            self.file_count_label.setText("当前: 使用目录扫描")
            return
        for p in sorted(self._selected_files):
            item = QListWidgetItem(p.name)
            item.setToolTip(str(p))
            self.file_list.addItem(item)
        self.file_count_label.setText(f"当前: 已选 {len(self._selected_files)} 张")

    def _start_stitch(self) -> None:
        input_text = self.dir_edit.text().strip()
        if not input_text and not self._selected_files:
            self._error("请先选择输入目录或图像文件")
            return

        input_dir = Path(input_text) if input_text else None
        expected_rows = self.rows_spin.value() or None
        expected_cols = self.cols_spin.value() or None

        config = StitchConfig(
            input_dir=input_dir,
            overlap_x=self.overlap_x_slider.value() / 100.0,
            overlap_y=self.overlap_y_slider.value() / 100.0,
            resolution_mode=str(self.resolution_mode_combo.currentData()),
            input_paths=self._selected_files or None,
            expected_rows=expected_rows,
            expected_cols=expected_cols,
            enable_exposure=self.exposure_cb.isChecked(),
            enable_align=self.align_cb.isChecked(),
            max_align_shift=self.align_shift_spin.value(),
        )

        self.status_label.setText("处理中...")
        self.progress.setValue(0)
        QApplication.processEvents()

        try:
            result = stitch(config, progress_callback=self._on_progress)
        except StitchError as exc:
            self._error(str(exc))
            self.status_label.setText("失败")
            self.progress.setValue(0)
            return
        except Exception as exc:  # noqa: BLE001
            self._error(f"发生未知错误: {exc}")
            self.status_label.setText("失败")
            self.progress.setValue(0)
            return

        self._last_result = result
        self._set_preview(result.preview)
        self.export_btn.setEnabled(True)
        self.progress.setValue(100)
        self.status_label.setText(
            f"完成: {result.rows}x{result.cols} 张, 单图 {result.tile_width}x{result.tile_height}; {result.source_size_summary}"
        )

    def _export_image(self) -> None:
        if self._last_result is None:
            self._error("没有可导出的拼接结果")
            return

        suggested_name = "stitched_output.png"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出拼接图",
            suggested_name,
            "PNG (*.png);;TIFF (*.tif *.tiff);;JPEG (*.jpg *.jpeg)",
        )
        if not output_path:
            return

        self.status_label.setText("导出中...")
        QApplication.processEvents()
        try:
            export_image(Path(output_path), self._last_result.image)
        except ExportError as exc:
            self._error(str(exc))
            self.status_label.setText("导出失败")
            return

        self.status_label.setText(f"导出成功: {output_path}")

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress.setValue(max(0, min(100, percent)))
        self.status_label.setText(message)
        QApplication.processEvents()

    def _set_preview(self, image_bgr) -> None:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._last_result is not None:
            self._set_preview(self._last_result.preview)

    def _error(self, text: str) -> None:
        QMessageBox.critical(self, "错误", text)


def run() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
