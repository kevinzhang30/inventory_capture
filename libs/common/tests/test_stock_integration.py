"""Exactly-once ledger semantics against a real Postgres (make up). Run: pytest -m integration."""

import os
import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture()
def conn():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    from inventory_common.db import get_pool

    with get_pool().connection() as c:
        c.execute("INSERT INTO site VALUES ('TST','Test','UTC') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO location VALUES ('TST-L1','TST','L1','bin') ON CONFLICT DO NOTHING")
        c.execute("""INSERT INTO part (sku, part_number, name, category, reorder_point)
                     VALUES ('TST-SKU','TST-PN','Test','test',3) ON CONFLICT DO NOTHING""")
        c.commit()
        yield c
        c.rollback()


def test_apply_movements_is_idempotent(conn):
    from inventory_common.stock import MovementIn, apply_movements

    key = f"{uuid.uuid4()}:0"
    m = MovementIn("TST-SKU", "TST-L1", 5, "receipt", key)
    with conn.transaction():
        before = conn.execute(
            "SELECT COALESCE(MAX(version),0) v FROM stock_level WHERE sku='TST-SKU' AND location_id='TST-L1'"
        ).fetchone()["v"]
        first = apply_movements(conn, [m])
        second = apply_movements(conn, [m])
    assert len(first) == 1 and second == []
    assert first[0]["version"] == before + 1
    assert first[0]["reorder_point"] == 3
    n = conn.execute("SELECT count(*) n FROM outbox WHERE payload->>'movement_id' = %s",
                     (str(first[0]["movement_id"]),)).fetchone()["n"]
    assert n == 1
