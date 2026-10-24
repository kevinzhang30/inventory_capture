import pytest

from ops import bootstrap


def test_db_dir_found_in_repo():
    assert (bootstrap.db_dir() / "migrations" / "versions").is_dir()


def test_run_orders_actions_and_retries(monkeypatch):
    calls = []
    flaky = {"n": 0}

    def topics():
        flaky["n"] += 1
        if flaky["n"] == 1:
            raise ConnectionError("broker not ready")
        calls.append("topics")
        return {}

    monkeypatch.setattr(bootstrap, "ACTIONS", {**bootstrap.ACTIONS, "migrate": lambda: calls.append("migrate"),
                                               "topics": topics})
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    bootstrap.run(["topics", "migrate"], retries=2)
    assert calls == ["migrate", "topics"]


def test_unknown_action():
    with pytest.raises(ValueError):
        bootstrap.run(["nope"])
