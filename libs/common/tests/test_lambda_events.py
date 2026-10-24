import base64
import json

from inventory_common import lambda_events, rabbit
from inventory_common.lambda_events import iter_kafka_records, iter_rmq_messages, rmq_consume


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def test_iter_kafka_records_decodes_key_value_headers():
    event = {
        "eventSource": "aws:kafka",
        "records": {
            "captures.raw-3": [
                {"topic": "captures.raw", "partition": 3, "offset": 7, "timestamp": 1,
                 "key": b64("cap-1"), "value": b64(json.dumps({"a": 1})),
                 "headers": [{"trace": list(b"t-1")}]},
            ]
        },
    }
    (rec,) = list(iter_kafka_records(event))
    assert (rec.topic, rec.partition, rec.offset, rec.key) == ("captures.raw", 3, 7, "cap-1")
    assert rec.json() == {"a": 1}
    assert rec.headers == {"trace": "t-1"}


def test_iter_rmq_messages_decodes_byte_headers():
    event = {"rmqMessagesByQueue": {"review.dispatch::/": [
        {"basicProperties": {"messageId": "m1", "headers": {"x-attempt": 2, "src": {"bytes": list(b"relay")}}},
         "redelivered": True, "data": b64('{"x": 1}')}]}}
    (msg,) = list(iter_rmq_messages(event))
    assert msg.queue == "review.dispatch"
    assert msg.headers == {"x-attempt": 2, "src": "relay"}
    assert msg.redelivered and msg.json() == {"x": 1}


def _event(headers):
    return {"rmqMessagesByQueue": {"notify::/": [
        {"basicProperties": {"messageId": "m1", "headers": headers}, "data": b64('{"k": 1}')}]}}


def test_rmq_consume_retries_then_dead_letters(monkeypatch):
    published = []
    monkeypatch.setattr(lambda_events.rabbit, "publish",
                        lambda q, p, h, exchange, message_id: published.append((q, exchange, h["x-attempt"])))

    def boom(_payload, _msg):
        raise RuntimeError("nope")

    assert rmq_consume(_event({}), boom)["retried"] == 1
    assert published[-1] == ("notify", rabbit.RETRY_EXCHANGE, 1)
    assert rmq_consume(_event({"x-attempt": rabbit.MAX_ATTEMPTS - 1}), boom)["dead_lettered"] == 1
    assert published[-1] == ("notify", rabbit.DLQ_EXCHANGE, rabbit.MAX_ATTEMPTS)


def test_rmq_consume_success():
    seen = []
    assert rmq_consume(_event({}), lambda p, m: seen.append(p))["ok"] == 1
    assert seen == [{"k": 1}]
