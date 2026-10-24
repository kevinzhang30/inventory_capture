"""Station configuration persisted with QSettings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platformdirs import user_data_dir
from PySide6.QtCore import QSettings

APP_NAME = "InventoryCapture"
ORG = "InventoryCapture"


@dataclass
class StationConfig:
    api_base_url: str = "http://localhost:8080"
    auth_mode: str = "dev"  # dev | cognito
    cognito_region: str = "us-east-1"
    cognito_client_id: str = ""
    username: str = ""
    site_id: str = "DAL1"
    station_id: str = "DAL1-DOCK-01"
    receiving_location: str = "DAL1-RECV-01"
    camera_index: int = 0

    @classmethod
    def load(cls) -> StationConfig:
        s = QSettings(ORG, APP_NAME)
        cfg = cls()
        for f in fields(cls):
            if s.contains(f.name):
                raw = s.value(f.name)
                setattr(cfg, f.name, int(raw) if f.type in ("int", int) else str(raw))
        return cfg

    def save(self) -> None:
        s = QSettings(ORG, APP_NAME)
        for k, v in asdict(self).items():
            s.setValue(k, v)
        s.sync()


def data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, ORG))
    path.mkdir(parents=True, exist_ok=True)
    return path
