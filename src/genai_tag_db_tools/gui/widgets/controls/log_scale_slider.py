from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from superqt import QRangeSlider


class LogScaleRangeSlider(QWidget):
    """Range slider with log-scale labels for usage count."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.slider = QRangeSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue((0, 100))

        self.min_label = QLabel("0")
        self.max_label = QLabel("100,000+")

        labels_layout = QHBoxLayout()
        labels_layout.addWidget(self.min_label)
        labels_layout.addStretch()
        labels_layout.addWidget(self.max_label)

        layout.addWidget(self.slider)
        layout.addLayout(labels_layout)

        self.slider.valueChanged.connect(self.update_labels)

    @Slot()
    def update_labels(self) -> None:
        min_val, max_val = self.slider.value()
        self.min_label.setText(f"{self.scale_to_count(min_val):,}")
        self.max_label.setText(f"{self.scale_to_count(max_val):,}")

    def scale_to_count(self, value: int) -> int:
        min_count = 0
        max_count = 100_000
        if value == 0:
            return min_count
        if value == 100:
            return max_count

        log_min = np.log1p(min_count + 1)
        log_max = np.log1p(max_count)
        log_value = log_min + (log_max - log_min) * (value / 100.0)
        return int(np.expm1(log_value))

    def get_range(self) -> tuple[int, int]:
        min_val, max_val = self.slider.value()
        return (self.scale_to_count(min_val), self.scale_to_count(max_val))
