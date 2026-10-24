from evalkit.generate_golden import generate
from evalkit.run import evaluate, load_golden, render_report
from extract.extractors.stub import StubExtractor


def test_generate_and_evaluate_with_stub(tmp_path):
    generate(tmp_path, count=6, seed=1, n_parts=50)
    items = load_golden(tmp_path)
    assert len(items) == 6
    perfect = evaluate(StubExtractor(error_rate=0.0), items, concurrency=2)
    assert perfect["document_exact_match"] == 1.0 and perfect["errors"] == 0
    noisy = evaluate(StubExtractor(error_rate=0.5), items, concurrency=2)
    assert noisy["document_exact_match"] < 1.0
    report = render_report("stub", "v1", len(items), noisy)
    assert "Calibration" in report and "| Document exact match |" in report
