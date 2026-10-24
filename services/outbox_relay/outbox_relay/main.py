"""outbox-relay: polls the transactional outbox and publishes to Kafka / RabbitMQ (ECS Fargate, one leader).

Leadership: a session-level `pg_try_advisory_lock` on a dedicated connection. Followers retry every 2 s; if the
leader's lock connection dies, the lock is released by Postgres and the leader stops publishing immediately.
"""

from __future__ import annotations

import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import psycopg
from psycopg.rows import dict_row

from inventory_common import kafka, rabbit
from inventory_common.config import database_dsn, settings
from inventory_common.db import Conn
from inventory_common.kafka import DeliveryTracker
from inventory_common.log import emit_metric, get_logger
from outbox_relay.publish import publish_batch

log = get_logger("outbox_relay")

LOCK_ID = 7_301_355_001  # arbitrary constant shared by all relay instances
LAG_EVERY_S = 10
CLEANUP_EVERY_S = 600

state = {"leader": False, "healthy": True, "last_loop": time.monotonic()}
stop = threading.Event()


def kafka_send(rows: list[dict[str, Any]]) -> dict[int, str]:
    tracker = DeliveryTracker()
    for r in rows:
        kafka.produce_json(
            r["topic_or_queue"], r["msg_key"], r["payload"], r["headers"] or {}, tracker.callback(str(r["id"]))
        )
    remaining = kafka.flush(30.0)
    failures = {int(k): v for k, v in tracker.failed.items()}
    if remaining:
        for r in rows:
            if str(r["id"]) not in tracker.delivered and r["id"] not in failures:
                failures[r["id"]] = "flush timeout"
    return failures


def rabbit_send(row: dict[str, Any]) -> None:
    rabbit.publish(row["topic_or_queue"], row["payload"], row["headers"] or {}, message_id=row["msg_key"])


def relay_once(conn: Conn) -> int:
    with conn.transaction():
        rows = conn.execute(
            """SELECT id, destination, topic_or_queue, msg_key, payload, headers
               FROM outbox WHERE sent_at IS NULL ORDER BY id
               LIMIT %s FOR UPDATE SKIP LOCKED""",
            (settings.outbox_batch_size,),
        ).fetchall()
        if not rows:
            return 0
        result = publish_batch(rows, kafka_send, rabbit_send)
        if result.sent:
            conn.execute("UPDATE outbox SET sent_at = now() WHERE id = ANY(%s)", (result.sent,))
        for row_id, err in result.failed.items():
            conn.execute(
                "UPDATE outbox SET attempts = attempts + 1, last_error = %s WHERE id = %s", (err, row_id)
            )
    if result.failed:
        log.warning("outbox publish failures", extra={"failed": len(result.failed), "sent": len(result.sent)})
        emit_metric("OutboxPublishFailures", len(result.failed))
    return len(result.sent)


def report_lag(conn: Conn) -> None:
    with conn.transaction():
        row = conn.execute(
            """SELECT EXTRACT(EPOCH FROM (now() - MIN(created_at))) * 1000 AS lag_ms, COUNT(*) AS n
               FROM outbox WHERE sent_at IS NULL"""
        ).fetchone()
    if row is None:
        return
    emit_metric("OutboxRelayLag", float(row["lag_ms"] or 0), "Milliseconds")
    emit_metric("OutboxUnsent", int(row["n"]))


def cleanup(conn: Conn) -> None:
    while not stop.is_set():
        with conn.transaction():
            n = conn.execute(
                """DELETE FROM outbox WHERE id IN (
                     SELECT id FROM outbox WHERE sent_at < now() - interval '3 days' LIMIT 5000)"""
            ).rowcount
        if n < 5000:
            return


def lock_alive(lock_conn: psycopg.Connection) -> bool:
    try:
        lock_conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


def run_leader(lock_conn: psycopg.Connection) -> None:
    rabbit.declare_topology()
    kafka.get_producer()
    last_lag = last_cleanup = 0.0
    with psycopg.connect(database_dsn(), row_factory=dict_row, autocommit=False) as conn:
        log.info("relay is leader; publishing")
        while not stop.is_set():
            state["last_loop"] = time.monotonic()
            if not lock_alive(lock_conn):
                log.error("lost leadership connection; stepping down")
                return
            sent = relay_once(conn)
            now = time.monotonic()
            if now - last_lag > LAG_EVERY_S:
                report_lag(conn)
                last_lag = now
            if now - last_cleanup > CLEANUP_EVERY_S:
                cleanup(conn)
                last_cleanup = now
            if sent == 0:
                stop.wait(settings.outbox_poll_interval_ms / 1000)


def main_loop() -> None:
    while not stop.is_set():
        try:
            with psycopg.connect(database_dsn(), autocommit=True) as lock_conn:
                row = lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()
                got = bool(row and row[0])
                if not got:
                    state["leader"] = False
                    state["last_loop"] = time.monotonic()
                    stop.wait(2)
                    continue
                state["leader"] = True
                run_leader(lock_conn)
        except Exception:  # noqa: BLE001 - keep the relay alive; ECS restarts us only on health failure
            log.exception("relay loop error; retrying")
            state["leader"] = False
            rabbit.reset()
            stop.wait(2)
    kafka.flush(10)


class Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        ok = time.monotonic() - state["last_loop"] < 60
        self.send_response(200 if ok else 503)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(f'{{"ok": {str(ok).lower()}, "leader": {str(state["leader"]).lower()}}}'.encode())

    def log_message(self, *args: Any) -> None:
        pass


def main() -> None:
    server = HTTPServer(("0.0.0.0", 8081), Health)  # noqa: S104
    threading.Thread(target=server.serve_forever, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    main_loop()
    server.shutdown()


if __name__ == "__main__":
    main()
