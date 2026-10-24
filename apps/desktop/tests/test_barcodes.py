from inventory_desktop.barcodes import ScanSession, classify


def test_classify():
    assert classify("LOC:dal1-a01-01").kind == "location"
    assert classify("DAL1-A01-01").kind == "location"
    assert classify("RNO1-RECV-01").kind == "location"
    assert classify("QTY:12").value == "12"
    assert classify(" sku-000123 ").value == "SKU-000123"
    assert classify("SKU-000123").kind == "item"


def test_scan_session_flow():
    s = ScanSession()
    assert s.feed("SKU-000001") == "scan a bin/location label first"
    s.feed("DAL1-A01-01")
    s.feed("QTY:5")
    assert s.feed("SKU-000001") == ("SKU-000001", 5, "DAL1-A01-01")
    assert s.feed("SKU-000002") == ("SKU-000002", 1, "DAL1-A01-01")  # qty resets, location sticks
    assert s.feed("QTY:0") == "quantity must be non-zero"
    assert len(s.committed) == 2
