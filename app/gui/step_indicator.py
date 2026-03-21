"""Step indicator toolbar: three clickable step buttons with progress state."""

from PySide6 import QtCore, QtWidgets

from ..i18n import tr, language_manager

_KEYS = ["step.scan", "step.stitch", "step.navigate"]


class StepIndicator(QtWidgets.QWidget):
    """Horizontal step bar with three clickable buttons.

    Signals
    -------
    step_clicked(int)
        Emitted when the user clicks a step button (0, 1, or 2).
    """

    step_clicked = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        self._completed: set[int] = set()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self._buttons: list[QtWidgets.QPushButton] = []
        for i in range(len(_KEYS)):
            btn = QtWidgets.QPushButton()
            btn.setCheckable(True)
            btn.setMinimumHeight(36)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i: self._on_clicked(idx))
            layout.addWidget(btn)
            if i < len(_KEYS) - 1:
                sep = QtWidgets.QLabel("───")
                sep.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                sep.setFixedWidth(40)
                sep.setStyleSheet("color: #666;")
                layout.addWidget(sep)
            self._buttons.append(btn)

        language_manager().language_changed.connect(self._retranslate_ui)
        self._retranslate_ui()

    def set_step(self, index: int):
        """Set the current step and mark previous steps as completed."""
        for i in range(index):
            self._completed.add(i)
        self._current = index
        self._refresh()

    def _on_clicked(self, index: int):
        self._current = index
        self._refresh()
        self.step_clicked.emit(index)

    @QtCore.Slot()
    def _retranslate_ui(self):
        self._refresh()

    def _refresh(self):
        labels = [tr(k) for k in _KEYS]
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == self._current)
            if i in self._completed and i != self._current:
                label = labels[i].replace("①", "✓").replace("②", "✓").replace("③", "✓")
                btn.setText(label)
                btn.setStyleSheet(
                    "QPushButton { background-color: #1a5e1a; color: #ccc; "
                    "font-weight: bold; border: none; padding: 6px 16px; }"
                    "QPushButton:hover { background-color: #237523; }"
                )
            elif i == self._current:
                btn.setText(labels[i])
                btn.setStyleSheet(
                    "QPushButton { background-color: #2a82da; color: white; "
                    "font-weight: bold; border: none; padding: 6px 16px; }"
                )
            else:
                btn.setText(labels[i])
                btn.setStyleSheet(
                    "QPushButton { background-color: #3a3a3a; color: #999; "
                    "border: none; padding: 6px 16px; }"
                    "QPushButton:hover { background-color: #4a4a4a; }"
                )
