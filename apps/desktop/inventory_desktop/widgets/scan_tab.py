"""Scan tab: USB HID keyboard-wedge input and camera decoding feed the same ScanSession."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from inventory_desktop.barcodes import ScanSession
from inventory_desktop.camera import CameraThread


class ScanTab(QWidget):
    def __init__(self, on_commit: Callable[[str, int, str], None], camera_index: int = 0, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.on_commit = on_commit
        self.session = ScanSession()
        self.camera_index = camera_index
        self.camera: CameraThread | None = None

        self.input = QLineEdit()
        self.input.setPlaceholderText("Scan a location label, then items (keyboard-wedge scanners type here)")
        self.input.returnPressed.connect(self._on_enter)
        self.location = QLabel("—")
        self.qty = QSpinBox()
        self.qty.setRange(-100000, 100000)
        self.qty.setValue(1)
        self.qty.valueChanged.connect(lambda v: setattr(self.session, "qty", v or 1))
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.last = QLabel("")

        self.cam_toggle = QCheckBox("Camera decoding")
        self.cam_toggle.toggled.connect(self._toggle_camera)
        self.preview = QLabel("Camera off")
        self.preview.setMinimumSize(480, 320)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#111;color:#aaa")

        manual = QPushButton("Commit typed SKU")
        manual.clicked.connect(self._on_enter)

        form = QFormLayout()
        form.addRow("Scan", self.input)
        form.addRow("Location", self.location)
        form.addRow("Quantity", self.qty)
        form.addRow("", manual)
        form.addRow("Status", self.status)
        form.addRow("Last capture", self.last)
        left = QVBoxLayout()
        left.addLayout(form)
        left.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(self.cam_toggle)
        right.addWidget(self.preview, 1)
        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addLayout(right, 1)

    def focus_input(self) -> None:
        self.input.setFocus()

    def _on_enter(self) -> None:
        text = self.input.text()
        self.input.clear()
        self.handle_code(text)

    def handle_code(self, raw: str) -> None:
        result = self.session.feed(raw)
        self.location.setText(self.session.location_id or "—")
        self.qty.blockSignals(True)
        self.qty.setValue(self.session.qty)
        self.qty.blockSignals(False)
        if isinstance(result, tuple):
            sku, qty, loc = result
            self.on_commit(sku, qty, loc)
            self.last.setText(f"{sku} × {qty} → {loc}")
            self.status.setText("Captured")
        else:
            self.status.setText(result)

    def _toggle_camera(self, on: bool) -> None:
        if on:
            self.camera = CameraThread(self.camera_index, decode=True)
            self.camera.frame.connect(self._show_frame)
            self.camera.decoded.connect(self.handle_code)
            self.camera.error.connect(self.status.setText)
            self.camera.start()
        elif self.camera is not None:
            self.camera.stop()
            self.camera = None
            self.preview.setText("Camera off")

    def _show_frame(self, img: QImage) -> None:
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def shutdown(self) -> None:
        if self.camera is not None:
            self.camera.stop()
