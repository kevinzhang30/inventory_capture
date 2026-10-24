"""Local SQLite outbox (F2): every capture is durable on the station before any network call.

States: pending → (documents only) uploaded → synced | rejected. Failed attempts reschedule with exponential
backoff and full jitter.
"""

from __future__ import annotations

import json
import random
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capture_client.ids import new_capture_id

BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 300.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
  capture_id      TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,
  site_id         TEXT NOT NULL,
  station_id      TEXT NOT NULL,
  captured_at     TEXT NOT NULL,
  payload         TEXT NOT NULL,
  file_path       TEXT,
  content_type    TEXT,
  s3_key          TEXT,
  status          TEXT NOT NULL DEFAULT 'pending',
  attempts        INTEGER NOT NULL DEFAULT 0,
  next_attempt_at REAL NOT NULL DEFAULT 0,
  last_error      TEXT,
  created_at      REAL NOT NULL,
  synced_at       REAL
);
CREATE INDEX IF NOT EXISTS captures_due ON captures (status, next_attempt_at);
"""


def backoff_delay(attempts: int, rng: random.Random | None = None) -> float:
    """Full jitter: uniform(0, min(cap, base * 2^attempts))."""
    ceiling = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** min(attempts, 20)))
    return (rng or random).uniform(0, ceiling)


@dataclass
class OutboxItem:
    capture_id: str
    kind: str
    site_id: str
    station_id: str
    captured_at: str
    payload: dict[str, Any]
    file_path: str | None
    content_type: str | None
    s3_key: str | None
    status: str
    attempts: int
    last_error: str | None

    def to_capture(self) -> dict[str, Any]:
        payload = dict(self.payload)
        if self.kind == "document":
            payload["s3_key"] = self.s3_key
            payload["content_type"] = self.content_type
        return {"capture_id": self.capture_id, "site_id": self.site_id, "station_id": self.station_id,
                "kind": self.kind, "captured_at": self.captured_at, "payload": payload}


class Outbox:
    def __init__(self, db_path: str | Path, files_dir: str | Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_dir = Path(files_dir) if files_dir else self.db_path.parent / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _insert(self, **row: Any) -> str:
        row.setdefault("capture_id", new_capture_id())
        row.setdefault("captured_at", self._now_iso())
        row["payload"] = json.dumps(row["payload"])
        row["created_at"] = time.time()
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        with self._lock:
            self._conn.execute(f"INSERT INTO captures ({cols}) VALUES ({marks})", row)  # noqa: S608
        return row["capture_id"]

    def add_scan(self, site_id: str, station_id: str, sku: str, qty: int, location_id: str) -> str:
        return self._insert(kind="scan", site_id=site_id, station_id=station_id,
                            payload={"sku": sku, "qty": qty, "location_id": location_id})

    def add_document(self, site_id: str, station_id: str, file_path: str | Path, content_type: str,
                     location_id: str, po_number: str | None = None) -> str:
        capture_id = new_capture_id()
        src = Path(file_path)
        dest = self.files_dir / f"{capture_id}{src.suffix.lower()}"
        shutil.copyfile(src, dest)  # keep our own copy: the original may be deleted before sync
        payload: dict[str, Any] = {"location_id": location_id}
        if po_number:
            payload["po_number"] = po_number
        return self._insert(capture_id=capture_id, kind="document", site_id=site_id, station_id=station_id,
                            payload=payload, file_path=str(dest), content_type=content_type)

    def _items(self, sql: str, params: tuple[Any, ...] = ()) -> list[OutboxItem]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [OutboxItem(capture_id=r["capture_id"], kind=r["kind"], site_id=r["site_id"],
                           station_id=r["station_id"], captured_at=r["captured_at"],
                           payload=json.loads(r["payload"]), file_path=r["file_path"],
                           content_type=r["content_type"], s3_key=r["s3_key"], status=r["status"],
                           attempts=r["attempts"], last_error=r["last_error"]) for r in rows]

    def due_uploads(self, limit: int = 10, now: float | None = None) -> list[OutboxItem]:
        return self._items(
            """SELECT * FROM captures WHERE kind = 'document' AND status = 'pending' AND next_attempt_at <= ?
               ORDER BY created_at LIMIT ?""",
            (now if now is not None else time.time(), limit),
        )

    def due_batch(self, limit: int = 50, now: float | None = None) -> list[OutboxItem]:
        """Captures ready to POST: scans that are pending, documents whose image is uploaded."""
        return self._items(
            """SELECT * FROM captures
               WHERE ((kind = 'scan' AND status = 'pending') OR (kind = 'document' AND status = 'uploaded'))
                 AND next_attempt_at <= ?
               ORDER BY created_at LIMIT ?""",
            (now if now is not None else time.time(), limit),
        )

    def mark_uploaded(self, capture_id: str, s3_key: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE captures SET status = 'uploaded', s3_key = ?, next_attempt_at = 0 WHERE capture_id = ?",
                (s3_key, capture_id),
            )

    def mark_synced(self, capture_ids: list[str]) -> None:
        with self._lock:
            self._conn.executemany(
                "UPDATE captures SET status = 'synced', synced_at = ?, last_error = NULL WHERE capture_id = ?",
                [(time.time(), c) for c in capture_ids],
            )

    def mark_rejected(self, capture_id: str, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE captures SET status = 'rejected', last_error = ? WHERE capture_id = ?", (error, capture_id)
            )

    def schedule_retry(self, capture_ids: list[str], error: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            for cid in capture_ids:
                row = self._conn.execute("SELECT attempts FROM captures WHERE capture_id = ?", (cid,)).fetchone()
                if row is None:
                    continue
                attempts = row["attempts"] + 1
                self._conn.execute(
                    "UPDATE captures SET attempts = ?, next_attempt_at = ?, last_error = ? WHERE capture_id = ?",
                    (attempts, now + backoff_delay(attempts), error[:500], cid),
                )

    def recent(self, limit: int = 200) -> list[OutboxItem]:
        return self._items("SELECT * FROM captures ORDER BY created_at DESC LIMIT ?", (limit,))

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM captures GROUP BY status").fetchall()
        out = {"pending": 0, "uploaded": 0, "synced": 0, "rejected": 0}
        out.update({r["status"]: r["n"] for r in rows})
        return out

    def purge_synced(self, older_than_s: float = 7 * 86400) -> int:
        cutoff = time.time() - older_than_s
        with self._lock:
            rows = self._conn.execute(
                "SELECT capture_id, file_path FROM captures WHERE status = 'synced' AND synced_at < ?", (cutoff,)
            ).fetchall()
            for r in rows:
                if r["file_path"]:
                    Path(r["file_path"]).unlink(missing_ok=True)
            self._conn.execute("DELETE FROM captures WHERE status = 'synced' AND synced_at < ?", (cutoff,))
        return len(rows)
