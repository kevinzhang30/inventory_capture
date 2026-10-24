-- Correctness drill (design §3 NFR "zero lost or duplicated stock movements"):
-- run after a load test with chaos (consumer kills). Every query should return zero rows / zero counts.

-- 1. Scans that were applied but have no ledger row (lost effect).
SELECT c.capture_id, c.received_at
FROM capture c
LEFT JOIN stock_movement m ON m.source_capture_id = c.capture_id
WHERE c.kind = 'scan' AND c.status = 'applied' AND m.movement_id IS NULL
LIMIT 50;

-- 2. Captures with more ledger rows than lines (duplicated effect). Scans must have exactly one.
SELECT m.source_capture_id, c.kind, COUNT(*) AS movements
FROM stock_movement m JOIN capture c ON c.capture_id = m.source_capture_id
GROUP BY m.source_capture_id, c.kind
HAVING (c.kind = 'scan' AND COUNT(*) > 1)
    OR COUNT(*) > COUNT(DISTINCT m.idempotency_key)
LIMIT 50;

-- 3. stock_level must equal the sum of the ledger for every (sku, location).
SELECT sl.sku, sl.location_id, sl.on_hand, COALESCE(SUM(m.qty_delta), 0) AS ledger
FROM stock_level sl
LEFT JOIN stock_movement m ON m.sku = sl.sku AND m.location_id = sl.location_id
GROUP BY sl.sku, sl.location_id, sl.on_hand
HAVING sl.on_hand <> COALESCE(SUM(m.qty_delta), 0)
LIMIT 50;

-- 4. Captures stuck before processing (should drain to 0 once consumers catch up).
SELECT status, COUNT(*) FROM capture WHERE status = 'received' GROUP BY status;

-- 5. Outbox backlog (should drain to 0).
SELECT COUNT(*) AS unsent, MIN(created_at) AS oldest FROM outbox WHERE sent_at IS NULL;

-- Summary
SELECT
  (SELECT COUNT(*) FROM capture WHERE kind = 'scan' AND status = 'applied') AS applied_scans,
  (SELECT COUNT(*) FROM stock_movement m JOIN capture c ON c.capture_id = m.source_capture_id
     WHERE c.kind = 'scan') AS scan_movements;
