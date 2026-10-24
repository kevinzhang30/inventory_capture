from outbox_relay.publish import publish_batch


def row(i, dest="kafka", key="SKU-1", topic="inventory.events"):
    return {"id": i, "destination": dest, "topic_or_queue": topic, "msg_key": key, "payload": {}, "headers": {}}


def test_all_sent():
    rows = [row(1), row(2, key="SKU-2"), row(3, dest="rabbitmq", topic="review.dispatch", key="c1")]
    res = publish_batch(rows, lambda rs: {}, lambda r: None)
    assert sorted(res.sent) == [1, 2, 3] and res.failed == {}


def test_failed_key_holds_back_later_rows_of_same_key():
    rows = [row(1), row(2), row(3, key="SKU-2"), row(4)]
    res = publish_batch(rows, lambda rs: {1: "timeout"}, lambda r: None)
    assert res.failed == {1: "timeout"}
    assert res.sent == [3]  # rows 2 and 4 (same key as failed row 1) stay unsent, not failed


def test_rabbit_failure_is_isolated():
    rows = [row(1, dest="rabbitmq", key="a"), row(2, dest="rabbitmq", key="b")]

    def send(r):
        if r["id"] == 1:
            raise ConnectionError("down")

    res = publish_batch(rows, lambda rs: {}, send)
    assert res.sent == [2] and set(res.failed) == {1}
