"""Sync engine: drains the local outbox to the ingest API with backoff (design §6.1)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from capture_client.api import ApiClient, ApiError
from capture_client.outbox import Outbox

RETRYABLE_ITEM_ERRORS = {"produce_failed", "rate_limited"}


@dataclass
class SyncStatus:
    online: bool = True
    uploaded: int = 0
    synced: int = 0
    rejected: int = 0
    retried: int = 0
    last_error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


class SyncEngine:
    def __init__(self, outbox: Outbox, api: ApiClient, batch_size: int = 50):
        self.outbox, self.api, self.batch_size = outbox, api, min(batch_size, 50)

    def sync_once(self) -> SyncStatus:
        st = SyncStatus()
        try:
            for item in self.outbox.due_uploads():
                try:
                    s3_key = self.api.upload_file(item.capture_id, item.file_path or "", item.content_type or "")
                    self.outbox.mark_uploaded(item.capture_id, s3_key)
                    st.uploaded += 1
                except ApiError as exc:
                    if exc.retryable:
                        self.outbox.schedule_retry([item.capture_id], str(exc))
                        st.retried += 1
                    else:
                        self.outbox.mark_rejected(item.capture_id, f"upload: {exc}")
                        st.rejected += 1
                except FileNotFoundError:
                    self.outbox.mark_rejected(item.capture_id, "image file missing")
                    st.rejected += 1

            while batch := self.outbox.due_batch(self.batch_size):
                ids = [i.capture_id for i in batch]
                try:
                    results = self.api.post_captures([i.to_capture() for i in batch])
                except ApiError as exc:
                    if exc.retryable:
                        self.outbox.schedule_retry(ids, str(exc))
                        st.retried += len(ids)
                    else:  # e.g. 400 for the whole batch: send items one by one next time would be nicer
                        for cid in ids:
                            self.outbox.mark_rejected(cid, str(exc))
                        st.rejected += len(ids)
                    break
                ok, retry = [], []
                for res in results:
                    if res["status"] in ("accepted", "duplicate"):
                        ok.append(res["capture_id"])
                    elif res.get("error") in RETRYABLE_ITEM_ERRORS:
                        retry.append(res["capture_id"])
                    else:
                        self.outbox.mark_rejected(res["capture_id"], res.get("error") or "rejected")
                        st.rejected += 1
                self.outbox.mark_synced(ok)
                st.synced += len(ok)
                if retry:
                    self.outbox.schedule_retry(retry, "retryable rejection")
                    st.retried += len(retry)
                if len(batch) < self.batch_size:
                    break
        except (httpx.TransportError, PermissionError) as exc:
            st.online = False
            st.last_error = str(exc)
            pending = [i.capture_id for i in self.outbox.due_batch(self.batch_size)]
            pending += [i.capture_id for i in self.outbox.due_uploads()]
            self.outbox.schedule_retry(pending, f"offline: {exc}")
        st.counts = self.outbox.stats()
        return st


class SyncWorker(threading.Thread):
    """Background loop; `on_status` is invoked from this thread (marshal to the UI thread yourself)."""

    def __init__(self, engine: SyncEngine, interval_s: float = 2.0,
                 on_status: Callable[[SyncStatus], None] | None = None):
        super().__init__(daemon=True, name="sync-worker")
        self.engine, self.interval_s, self.on_status = engine, interval_s, on_status
        self._stop = threading.Event()
        self._wake = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            status = self.engine.sync_once()
            if self.on_status:
                self.on_status(status)
            self._wake.wait(self.interval_s if status.online else self.interval_s * 5)
            self._wake.clear()

    def sync_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
