"""Outbox panel: recent captures, sync counters and connectivity."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capture_client.outbox import OutboxItem
from capture_client.sync import SyncStatus

COLUMNS = ["Captured", "Kind", "Summary", "Status", "Attempts", "Error"]


class OutboxPanel(QWidget):
    def __init__(self, on_sync_now, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.conn = QLabel("● online")
        self.counts = QLabel("")
        sync = QPushButton("Sync now")
        sync.clicked.connect(on_sync_now)
        top = QHBoxLayout()
        top.addWidget(self.conn)
        top.addWidget(self.counts, 1)
        top.addWidget(sync)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)

    def update_status(self, st: SyncStatus) -> None:
        self.conn.setText("● online" if st.online else f"● offline ({st.last_error or 'retrying'})")
        self.conn.setStyleSheet("color:#1b873f" if st.online else "color:#b00020")
        c = st.counts
        self.counts.setText(f"pending {c.get('pending', 0) + c.get('uploaded', 0)} · synced {c.get('synced', 0)} · "
                            f"rejected {c.get('rejected', 0)}")

    def update_items(self, items: list[OutboxItem]) -> None:
        self.table.setRowCount(len(items))
        for row, it in enumerate(items):
            summary = (f"{it.payload.get('sku')} × {it.payload.get('qty')} @ {it.payload.get('location_id')}"
                       if it.kind == "scan" else f"slip @ {it.payload.get('location_id')}")
            for col, val in enumerate((it.captured_at[11:19], it.kind, summary, it.status, str(it.attempts),
                                       it.last_error or "")):
                self.table.setItem(row, col, QTableWidgetItem(val))
