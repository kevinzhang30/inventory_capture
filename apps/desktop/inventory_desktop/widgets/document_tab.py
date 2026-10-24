"""Document tab: packing-slip photo from the camera or a file (jpg/png/pdf)."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from inventory_desktop.camera import CameraThread

CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}


class DocumentTab(QWidget):
    def __init__(self, on_capture: Callable[[Path, str, str, str | None], None], default_location: str,
                 camera_index: int = 0, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.on_capture = on_capture
        self.camera_index = camera_index
        self.camera: CameraThread | None = None
        self.pending: Path | None = None

        self.location = QLineEdit(default_location)
        self.po_hint = QLineEdit()
        self.po_hint.setPlaceholderText("optional PO number hint")
        self.preview = QLabel("No document")
        self.preview.setMinimumSize(480, 360)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#111;color:#aaa")

        cam_btn = QPushButton("Start camera")
        cam_btn.setCheckable(True)
        cam_btn.toggled.connect(self._toggle_camera)
        snap_btn = QPushButton("Take photo")
        snap_btn.clicked.connect(self._snapshot)
        file_btn = QPushButton("Choose file…")
        file_btn.clicked.connect(self._choose_file)
        self.submit_btn = QPushButton("Queue document capture")
        self.submit_btn.setEnabled(False)
        self.submit_btn.clicked.connect(self._submit)

        form = QFormLayout()
        form.addRow("Receiving location", self.location)
        form.addRow("PO hint", self.po_hint)
        buttons = QHBoxLayout()
        for b in (cam_btn, snap_btn, file_btn, self.submit_btn):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.preview, 1)

    def _toggle_camera(self, on: bool) -> None:
        if on:
            self.camera = CameraThread(self.camera_index, decode=False)
            self.camera.frame.connect(self._show)
            self.camera.error.connect(lambda m: QMessageBox.warning(self, "Camera", m))
            self.camera.start()
        elif self.camera:
            self.camera.stop()
            self.camera = None

    def _show(self, img: QImage) -> None:
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _snapshot(self) -> None:
        data = self.camera.snapshot_jpeg() if self.camera else None
        if not data:
            QMessageBox.information(self, "Camera", "Start the camera first")
            return
        tmp = Path(tempfile.mkstemp(suffix=".jpg")[1])
        tmp.write_bytes(data)
        self._set_pending(tmp)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Packing slip", "", "Documents (*.jpg *.jpeg *.png *.pdf)")
        if path:
            self._set_pending(Path(path))

    def _set_pending(self, path: Path) -> None:
        self.pending = path
        if path.suffix.lower() == ".pdf":
            self.preview.setText(f"PDF: {path.name}")
        else:
            self.preview.setPixmap(QPixmap(str(path)).scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.submit_btn.setEnabled(True)

    def _submit(self) -> None:
        if self.pending is None:
            return
        ctype = CONTENT_TYPES.get(self.pending.suffix.lower())
        if ctype is None:
            QMessageBox.warning(self, "Unsupported", "Use a JPG, PNG or PDF")
            return
        self.on_capture(self.pending, ctype, self.location.text().strip().upper(), self.po_hint.text().strip() or None)
        self.pending = None
        self.po_hint.clear()
        self.submit_btn.setEnabled(False)
        self.preview.setText("Queued ✓ — capture the next slip")

    def shutdown(self) -> None:
        if self.camera:
            self.camera.stop()
