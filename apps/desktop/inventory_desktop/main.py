"""Entry point and main window: wires the local outbox, sync worker and capture tabs."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QSplitter, QTabWidget

from capture_client.api import ApiClient, CognitoAuth, DevAuth
from capture_client.outbox import Outbox
from capture_client.sync import SyncEngine, SyncStatus, SyncWorker
from inventory_desktop.config import StationConfig, data_dir
from inventory_desktop.widgets.dialogs import LoginDialog, SettingsDialog
from inventory_desktop.widgets.document_tab import DocumentTab
from inventory_desktop.widgets.outbox_panel import OutboxPanel
from inventory_desktop.widgets.scan_tab import ScanTab


class Bridge(QObject):
    """Marshals sync-thread callbacks onto the Qt UI thread."""

    status = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, cfg: StationConfig):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle(f"Inventory Capture — {cfg.station_id}")
        self.resize(1200, 800)
        self.outbox = Outbox(data_dir() / "outbox.db")
        self.bridge = Bridge()
        self.bridge.status.connect(self._on_status)
        self.worker: SyncWorker | None = None

        self.scan_tab = ScanTab(self._commit_scan, cfg.camera_index)
        self.doc_tab = DocumentTab(self._commit_document, cfg.receiving_location, cfg.camera_index)
        tabs = QTabWidget()
        tabs.addTab(self.scan_tab, "Scan")
        tabs.addTab(self.doc_tab, "Packing slip")
        self.panel = OutboxPanel(self._sync_now)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(tabs)
        split.addWidget(self.panel)
        self.setCentralWidget(split)

        settings = QAction("Settings…", self)
        settings.triggered.connect(self._settings)
        self.menuBar().addMenu("&Station").addAction(settings)

        self.refresh = QTimer(self)
        self.refresh.timeout.connect(lambda: self.panel.update_items(self.outbox.recent(200)))
        self.refresh.start(1000)
        self._start_sync()
        self.scan_tab.focus_input()

    def _auth(self):  # type: ignore[no-untyped-def]
        if self.cfg.auth_mode == "dev":
            return DevAuth(user=self.cfg.station_id.lower(), groups="operator")
        auth = CognitoAuth(self.cfg.cognito_region, self.cfg.cognito_client_id, self.cfg.username)
        if auth.has_refresh_token():
            return auth
        dlg = LoginDialog(self.cfg.username, self)
        while dlg.exec():
            try:
                auth = CognitoAuth(self.cfg.cognito_region, self.cfg.cognito_client_id, dlg.user.text().strip())
                auth.login(dlg.password.text())
                self.cfg.username = dlg.user.text().strip()
                self.cfg.save()
                return auth
            except Exception as exc:  # noqa: BLE001 - show any auth failure to the operator
                dlg.show_error(str(exc))
        return None

    def _start_sync(self) -> None:
        if self.worker:
            self.worker.stop()
        auth = self._auth()
        if auth is None:
            QMessageBox.warning(self, "Offline", "Not signed in: captures are queued locally until you sign in.")
            return
        engine = SyncEngine(self.outbox, ApiClient(self.cfg.api_base_url, auth))
        self.worker = SyncWorker(engine, on_status=self.bridge.status.emit)
        self.worker.start()

    def _on_status(self, st: SyncStatus) -> None:
        self.panel.update_status(st)

    def _sync_now(self) -> None:
        if self.worker:
            self.worker.sync_now()
        else:
            self._start_sync()

    def _commit_scan(self, sku: str, qty: int, location_id: str) -> None:
        self.outbox.add_scan(self.cfg.site_id, self.cfg.station_id, sku, qty, location_id)
        self._sync_now()

    def _commit_document(self, path: Path, content_type: str, location_id: str, po: str | None) -> None:
        self.outbox.add_document(self.cfg.site_id, self.cfg.station_id, path, content_type, location_id, po)
        self._sync_now()

    def _settings(self) -> None:
        if SettingsDialog(self.cfg, self).exec():
            self._start_sync()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.scan_tab.shutdown()
        self.doc_tab.shutdown()
        if self.worker:
            self.worker.stop()
        self.outbox.purge_synced()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Inventory Capture")
    win = MainWindow(StationConfig.load())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
