from eval_nightly.metrics import calibration, compute_metrics, recommend_threshold, score_document


def f(v, c=0.95):
    return {"value": v, "confidence": c}


def out(items, supplier="SUP-A", po="PO-1", conf=0.95):
    return {"supplier": f(supplier, conf), "po_number": f(po, conf),
            "line_items": [{"line_no": i + 1, "sku": f(s, conf), "part_number": f(None, 0), "qty": f(q, conf)}
                           for i, (s, q) in enumerate(items)]}


def truth(items, supplier="SUP-A", po="PO-1"):
    return {"supplier": supplier, "po_number": po,
            "line_items": [{"line_no": i + 1, "sku": s, "qty": q, "location_id": "L"}
                           for i, (s, q) in enumerate(items)]}


ITEMS = [("SKU-1", 5), ("SKU-2", 3)]


def test_perfect():
    m = compute_metrics([(out(ITEMS), truth(ITEMS))] * 3, min_samples=1)
    assert m["fields"]["sku"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert m["fields"]["supplier"]["accuracy"] == 1.0 and m["fields"]["qty"]["accuracy"] == 1.0
    assert m["line_item_exact_match"] == 1.0 and m["document_exact_match"] == 1.0
    assert m["n_extractions"] == 3 and m["n_line_items"] == 6


def test_all_wrong():
    m = compute_metrics([(out([("SKU-9", 1), ("SKU-8", 1)], "X", "Y"), truth(ITEMS))], min_samples=1)
    assert m["fields"]["sku"]["precision"] == 0.0 and m["fields"]["sku"]["f1"] == 0.0
    assert m["document_exact_match"] == 0.0 and m["fields"]["supplier"]["accuracy"] == 0.0


def test_partial_and_missing_line():
    d = score_document(out([("SKU-1", 5)]), truth(ITEMS))
    assert (d.sku_tp, d.sku_pred, d.sku_truth) == (1, 1, 2)
    assert not d.stock_correct and d.supplier_ok
    m = compute_metrics([(out([("SKU-1", 5)]), truth(ITEMS))], min_samples=1)
    assert m["fields"]["sku"]["precision"] == 1.0 and m["fields"]["sku"]["recall"] == 0.5
    assert m["line_item_exact_match"] == 0.5


def test_match_by_sku_when_line_numbers_shift():
    o = out(ITEMS)
    o["line_items"][0]["line_no"], o["line_items"][1]["line_no"] = 7, 8
    assert score_document(o, truth(ITEMS)).items_exact == 2


def test_calibration_bins_and_ece():
    bins, ece = calibration([(0.95, True), (0.95, False), (0.15, False)])
    assert bins[9]["count"] == 2 and bins[9]["accuracy"] == 0.5 and bins[1]["count"] == 1
    assert ece == round(2 / 3 * 0.45 + 1 / 3 * 0.15, 4)
    assert calibration([]) == (calibration([])[0], None)


def test_recommend_threshold():
    good = [score_document(out(ITEMS, conf=0.9), truth(ITEMS)) for _ in range(40)]
    bad = [score_document(out([("SKU-9", 1), ("SKU-2", 3)], conf=0.7), truth(ITEMS)) for _ in range(20)]
    assert recommend_threshold(good + bad, 0.98, min_samples=50) == 0.71
    assert recommend_threshold(good + bad, 0.98, min_samples=100) is None
    assert recommend_threshold(bad * 3, 0.98, min_samples=50) is None
