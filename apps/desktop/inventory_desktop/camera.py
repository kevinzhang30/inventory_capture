"""Camera capture thread: frame preview, barcode decoding (pyzbar) and still snapshots."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

DEDUPE_WINDOW_S = 1.5


class CameraThread(QThread):
    frame = Signal(QImage)
    decoded = Signal(str)
    error = Signal(str)

    def __init__(self, index: int = 0, decode: bool = True):
        super().__init__()
        self.index, self.decode = index, decode
        self._running = False
        self._last_frame: Any = None
        self._recent: dict[str, float] = {}

    def run(self) -> None:
        try:
            import cv2
        except ImportError:
            self.error.emit("opencv is not installed")
            return
        decoder = None
        if self.decode:
            try:
                from pyzbar import pyzbar  # needs the native zbar library

                decoder = pyzbar.decode
            except (ImportError, OSError):
                self.error.emit("zbar library not found; camera decoding disabled (HID scanners still work)")
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            self.error.emit(f"cannot open camera {self.index}")
            return
        self._running = True
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    self.msleep(30)
                    continue
                self._last_frame = frame
                if decoder is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    for sym in decoder(gray):
                        self._emit_decoded(sym.data.decode("utf-8", "replace"))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                self.frame.emit(QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy())
                self.msleep(33)
        finally:
            cap.release()

    def _emit_decoded(self, text: str) -> None:
        now = time.monotonic()
        if now - self._recent.get(text, 0.0) >= DEDUPE_WINDOW_S:
            self._recent[text] = now
            self.decoded.emit(text)

    def snapshot_jpeg(self) -> bytes | None:
        if self._last_frame is None:
            return None
        import cv2

        ok, buf = cv2.imencode(".jpg", self._last_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        return bytes(buf) if ok else None

    def stop(self) -> None:
        self._running = False
        self.wait(2000)
