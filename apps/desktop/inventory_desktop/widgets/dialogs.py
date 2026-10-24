"""Settings and Cognito login dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from inventory_desktop.config import StationConfig


class SettingsDialog(QDialog):
    def __init__(self, cfg: StationConfig, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("Station settings")
        self.cfg = cfg
        form = QFormLayout()
        self.api = QLineEdit(cfg.api_base_url)
        self.mode = QComboBox()
        self.mode.addItems(["dev", "cognito"])
        self.mode.setCurrentText(cfg.auth_mode)
        self.region = QLineEdit(cfg.cognito_region)
        self.client_id = QLineEdit(cfg.cognito_client_id)
        self.site = QLineEdit(cfg.site_id)
        self.station = QLineEdit(cfg.station_id)
        self.recv = QLineEdit(cfg.receiving_location)
        self.camera = QSpinBox()
        self.camera.setRange(0, 9)
        self.camera.setValue(cfg.camera_index)
        for label, w in (("API base URL", self.api), ("Auth mode", self.mode), ("Cognito region", self.region),
                         ("Cognito client ID", self.client_id), ("Site", self.site), ("Station", self.station),
                         ("Receiving location", self.recv), ("Camera index", self.camera)):
            form.addRow(label, w)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _save(self) -> None:
        if not self.api.text().startswith(("http://", "https://")):
            QMessageBox.warning(self, "Invalid", "API base URL must start with http:// or https://")
            return
        c = self.cfg
        c.api_base_url, c.auth_mode = self.api.text().rstrip("/"), self.mode.currentText()
        c.cognito_region, c.cognito_client_id = self.region.text().strip(), self.client_id.text().strip()
        c.site_id, c.station_id = self.site.text().strip().upper(), self.station.text().strip().upper()
        c.receiving_location, c.camera_index = self.recv.text().strip().upper(), self.camera.value()
        c.save()
        self.accept()


class LoginDialog(QDialog):
    """Collects credentials; the caller performs CognitoAuth.login so errors can be shown here."""

    def __init__(self, username: str = "", parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("Sign in")
        self.user = QLineEdit(username)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #b00020")
        form = QFormLayout()
        form.addRow("Username", self.user)
        form.addRow("Password", self.password)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    def show_error(self, msg: str) -> None:
        self.error.setText(msg)
