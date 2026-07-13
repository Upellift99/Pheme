import asyncio
import json

import httpx
import pytest

from pheme.huawei_client import Sms
from pheme.matrix_client import MatrixClient, MatrixMessage

HOMESERVER = "https://matrix.example.org"
ROOM = "!room:example.org"
USER = "@phemebot:example.org"
TOKEN = "tok"


def make_client(handler, homeserver=HOMESERVER):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MatrixClient(homeserver, TOKEN, ROOM, USER, http=http)


def run(coro):
    return asyncio.run(coro)


# --- sending -----------------------------------------------------------


def test_notify_sends_plain_text_message():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"event_id": "$evt1"})

    client = make_client(handler)
    try:
        assert run(client.notify("hello")) == "$evt1"
    finally:
        run(client.aclose())

    req = requests[0]
    assert req.method == "PUT"
    assert "/send/m.room.message/" in req.url.path
    assert req.headers["Authorization"] == "Bearer tok"
    assert json.loads(req.content) == {"msgtype": "m.text", "body": "hello"}


def test_relay_sms_formats_body_and_uses_index_txn():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["content"] = json.loads(request.content)
        return httpx.Response(200, json={"event_id": "$evt2"})

    client = make_client(handler)
    sms = Sms(index=42, phone="+33612345678", content="hi & bye", date="2026-07-01", unread=True)
    try:
        assert run(client.relay_sms(sms)) == "$evt2"
    finally:
        run(client.aclose())

    assert "pheme-sms-42" in captured["url"]
    content = captured["content"]
    assert content["body"] == "SMS from +33612345678 (2026-07-01):\nhi & bye"
    assert content["format"] == "org.matrix.custom.html"
    assert "<strong>SMS from +33612345678</strong>" in content["formatted_body"]
    assert "hi &amp; bye" in content["formatted_body"]  # HTML-escaped


def test_relay_sms_falls_back_to_unknown_sender():
    captured = {}

    def handler(request):
        captured["content"] = json.loads(request.content)
        return httpx.Response(200, json={"event_id": "$e"})

    client = make_client(handler)
    sms = Sms(index=1, phone="", content="c", date="d", unread=False)
    try:
        run(client.relay_sms(sms))
    finally:
        run(client.aclose())

    assert captured["content"]["body"].startswith("SMS from unknown (")


def test_send_returns_none_when_event_id_absent():
    def handler(request):
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        assert run(client.notify("x")) is None
    finally:
        run(client.aclose())


def test_send_raises_for_error_status():
    def handler(request):
        return httpx.Response(500, json={"errcode": "M_UNKNOWN"})

    client = make_client(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            run(client.notify("x"))
    finally:
        run(client.aclose())


def test_homeserver_trailing_slash_is_stripped():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"event_id": "$e"})

    client = make_client(handler, homeserver=HOMESERVER + "/")
    try:
        run(client.notify("x"))
    finally:
        run(client.aclose())

    assert "//_matrix" not in str(requests[0].url)


# --- receiving ---------------------------------------------------------


def test_initial_sync_token_uses_zero_timeout():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"next_batch": "s1"})

    client = make_client(handler)
    try:
        assert run(client.initial_sync_token()) == "s1"
    finally:
        run(client.aclose())

    assert captured["params"]["timeout"] == "0"
    assert "filter" in captured["params"]


def test_sync_returns_next_batch_and_messages():
    data = {
        "next_batch": "s2",
        "rooms": {
            "join": {
                ROOM: {
                    "timeline": {
                        "events": [
                            {
                                "type": "m.room.message",
                                "event_id": "$m1",
                                "sender": "@alice:example.org",
                                "content": {"msgtype": "m.text", "body": "!reply hi"},
                            }
                        ]
                    }
                }
            }
        },
    }

    def handler(request):
        return httpx.Response(200, json=data)

    client = make_client(handler)
    try:
        next_batch, messages = run(client.sync("s1"))
    finally:
        run(client.aclose())

    assert next_batch == "s2"
    assert messages == [
        MatrixMessage(event_id="$m1", sender="@alice:example.org", body="!reply hi")
    ]


# --- _extract_room_messages (pure) ------------------------------------


def _extractor():
    return make_client(lambda request: httpx.Response(200))


def test_extract_returns_empty_when_room_absent():
    client = _extractor()
    assert client._extract_room_messages({}) == []
    assert client._extract_room_messages({"rooms": {"join": {}}}) == []


def test_extract_skips_non_message_and_non_text_events():
    client = _extractor()
    data = {
        "rooms": {
            "join": {
                ROOM: {
                    "timeline": {
                        "events": [
                            {"type": "m.room.member", "content": {}},
                            {
                                "type": "m.room.message",
                                "content": {"msgtype": "m.image", "body": "pic"},
                            },
                            {
                                "type": "m.room.message",
                                "event_id": "$ok",
                                "sender": "@a:x",
                                "content": {"msgtype": "m.text", "body": "keep"},
                            },
                        ]
                    }
                }
            }
        }
    }
    assert client._extract_room_messages(data) == [
        MatrixMessage(event_id="$ok", sender="@a:x", body="keep")
    ]


def test_extract_defaults_missing_fields_to_empty_string():
    client = _extractor()
    data = {
        "rooms": {
            "join": {
                ROOM: {
                    "timeline": {
                        "events": [{"type": "m.room.message", "content": {"msgtype": "m.text"}}]
                    }
                }
            }
        }
    }
    assert client._extract_room_messages(data) == [MatrixMessage(event_id="", sender="", body="")]
