import asyncio

import pytest

from pheme import loops
from pheme.config import Config
from pheme.huawei_client import Sms
from pheme.matrix_client import MatrixMessage

BOT = "@phemebot:example.org"
USER = "@alice:example.org"


def make_cfg(**overrides):
    base = dict(
        huawei_host="192.168.8.1",
        huawei_user="admin",
        huawei_password="pw",
        matrix_homeserver="https://matrix.example.org",
        matrix_token="tok",
        matrix_user_id=BOT,
        matrix_room_id="!room:example.org",
        poll_interval=60,
        state_db=":memory:",
        mark_as_read=False,
        delete_after_relay=False,
        allow_outbound=True,
        log_level="INFO",
    )
    base.update(overrides)
    return Config(**base)


def sms(index, phone="+33612345678", content="hi", date="2026-07-01", unread=True):
    return Sms(index=index, phone=phone, content=content, date=date, unread=unread)


class FakeHuawei:
    def __init__(self):
        self.inbox = []
        self.list_error = None
        self.finalize_calls = []
        self.sent = []
        self.send_result = "OK"
        self.send_error = None

    def list_inbox(self):
        if self.list_error is not None:
            raise self.list_error
        return list(self.inbox)

    def finalize(self, read_indices, delete_indices):
        self.finalize_calls.append((read_indices, delete_indices))

    def send_sms(self, number, text):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((number, text))
        return self.send_result


class FakeMatrix:
    def __init__(self):
        self.relayed = []
        self.notifications = []
        self.initial_side_effects = None
        self.initial_calls = 0
        self.sync_side_effects = []
        self.sync_calls = 0

    async def relay_sms(self, s):
        self.relayed.append(s)
        return "$evt"

    async def notify(self, text):
        self.notifications.append(text)

    async def initial_sync_token(self):
        self.initial_calls += 1
        if self.initial_side_effects:
            effect = self.initial_side_effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            return effect
        return "s0"

    async def sync(self, since):
        self.sync_calls += 1
        if self.sync_side_effects:
            effect = self.sync_side_effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            return effect
        raise asyncio.CancelledError


class FakeStore:
    def __init__(self, sync_token=None, last_phone=None):
        self.relayed_indices = set()
        self.marks = []
        self.sync_token = sync_token
        self.last_phone = last_phone

    def is_relayed(self, index):
        return index in self.relayed_indices

    def mark_relayed(self, index, phone, date):
        self.marks.append((index, phone, date))
        self.relayed_indices.add(index)
        self.last_phone = phone

    def get_sync_token(self):
        return self.sync_token

    def set_sync_token(self, token):
        self.sync_token = token

    def last_inbound_phone(self):
        return self.last_phone


@pytest.fixture
def record_sleep(monkeypatch):
    """Replace asyncio.sleep with a recorder that stops loops after one call."""
    calls = []

    async def fake_sleep(delay):
        calls.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr(loops.asyncio, "sleep", fake_sleep)
    return calls


@pytest.fixture
def quiet_sleep(monkeypatch):
    """Replace asyncio.sleep with a no-op recorder (loops broken elsewhere)."""
    calls = []

    async def fake_sleep(delay):
        calls.append(delay)

    monkeypatch.setattr(loops.asyncio, "sleep", fake_sleep)
    return calls


# --- Backoff -----------------------------------------------------------


def test_backoff_grows_exponentially_and_caps():
    backoff = loops.Backoff(base=5.0, factor=2.0, maximum=20.0)
    assert backoff.next() == 5.0
    assert backoff.next() == 10.0
    assert backoff.next() == 20.0
    assert backoff.next() == 20.0  # capped


def test_backoff_reset_restarts_sequence():
    backoff = loops.Backoff(base=5.0, factor=2.0, maximum=300.0)
    backoff.next()
    backoff.next()
    backoff.reset()
    assert backoff.next() == 5.0


# --- inbound_loop ------------------------------------------------------


def test_inbound_relays_new_and_skips_relayed(record_sleep):
    huawei = FakeHuawei()
    huawei.inbox = [sms(1), sms(2)]
    matrix = FakeMatrix()
    store = FakeStore()
    store.relayed_indices.add(2)  # already relayed
    cfg = make_cfg()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.inbound_loop(cfg, huawei, matrix, store))

    assert [s.index for s in matrix.relayed] == [1]
    assert store.marks == [(1, "+33612345678", "2026-07-01")]
    assert huawei.finalize_calls == []  # flags off
    assert record_sleep == [60]  # poll_interval


def test_inbound_finalizes_read_and_delete(record_sleep):
    huawei = FakeHuawei()
    huawei.inbox = [sms(1, unread=True), sms(2, unread=False)]
    matrix = FakeMatrix()
    store = FakeStore()
    cfg = make_cfg(mark_as_read=True, delete_after_relay=True)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.inbound_loop(cfg, huawei, matrix, store))

    # Only unread messages are marked read; all relayed ones are deleted.
    assert huawei.finalize_calls == [([1], [1, 2])]


def test_inbound_backs_off_on_error(record_sleep):
    huawei = FakeHuawei()
    huawei.list_error = RuntimeError("cpe down")
    matrix = FakeMatrix()
    store = FakeStore()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.inbound_loop(make_cfg(), huawei, matrix, store))

    assert record_sleep == [5.0]  # first backoff delay
    assert matrix.relayed == []


# --- outbound_loop -----------------------------------------------------


def test_outbound_disabled_returns_immediately():
    matrix = FakeMatrix()
    cfg = make_cfg(allow_outbound=False)
    asyncio.run(loops.outbound_loop(cfg, FakeHuawei(), matrix, FakeStore()))
    assert matrix.sync_calls == 0
    assert matrix.notifications == []


def test_outbound_fetches_initial_token_with_retry(quiet_sleep):
    matrix = FakeMatrix()
    matrix.initial_side_effects = [RuntimeError("transient"), "s1"]
    store = FakeStore(sync_token=None)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.outbound_loop(make_cfg(), FakeHuawei(), matrix, store))

    assert matrix.initial_calls == 2
    assert store.sync_token == "s1"
    assert quiet_sleep == [5.0]  # one backoff during the retry


def test_outbound_processes_messages_and_advances_token(quiet_sleep):
    matrix = FakeMatrix()
    msg = MatrixMessage(event_id="$1", sender=USER, body="just chatting")
    matrix.sync_side_effects = [("s1", [msg])]
    store = FakeStore(sync_token="s0")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.outbound_loop(make_cfg(), FakeHuawei(), matrix, store))

    assert matrix.sync_calls == 2  # one that returns, one that stops
    assert store.sync_token == "s1"


def test_outbound_backs_off_on_sync_error(quiet_sleep):
    matrix = FakeMatrix()
    # First sync raises a transient error, second stops the loop.
    matrix.sync_side_effects = [RuntimeError("sync boom")]
    store = FakeStore(sync_token="s0")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.outbound_loop(make_cfg(), FakeHuawei(), matrix, store))

    assert quiet_sleep == [5.0]  # backoff after the error


def test_outbound_initial_token_propagates_cancellation(quiet_sleep):
    matrix = FakeMatrix()
    matrix.initial_side_effects = [asyncio.CancelledError()]
    store = FakeStore(sync_token=None)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.outbound_loop(make_cfg(), FakeHuawei(), matrix, store))

    assert matrix.initial_calls == 1
    assert quiet_sleep == []  # cancellation is re-raised, not backed off


# --- _handle_message ---------------------------------------------------


def handle(cfg, huawei, matrix, store, body, sender=USER):
    msg = MatrixMessage(event_id="$e", sender=sender, body=body)
    asyncio.run(loops._handle_message(cfg, huawei, matrix, store, msg))


def test_handle_ignores_non_command():
    matrix, huawei = FakeMatrix(), FakeHuawei()
    handle(make_cfg(), huawei, matrix, FakeStore(), "hello room")
    assert matrix.notifications == []
    assert huawei.sent == []


def test_handle_own_message_ignored():
    matrix, huawei = FakeMatrix(), FakeHuawei()
    handle(make_cfg(), huawei, matrix, FakeStore(), "!sms +33612345678 hi", sender=BOT)
    assert huawei.sent == []


def test_handle_usage_notifies():
    matrix = FakeMatrix()
    handle(make_cfg(), FakeHuawei(), matrix, FakeStore(), "!sms")
    assert matrix.notifications
    assert "Usage" in matrix.notifications[0]


def test_handle_reply_without_previous_sender():
    matrix = FakeMatrix()
    handle(make_cfg(), FakeHuawei(), matrix, FakeStore(last_phone=None), "!reply hi")
    assert matrix.notifications == ["No previous inbound sender to reply to."]


def test_handle_reply_uses_last_inbound_phone():
    matrix, huawei = FakeMatrix(), FakeHuawei()
    handle(make_cfg(), huawei, matrix, FakeStore(last_phone="+33111111111"), "!reply on my way")
    assert huawei.sent == [("+33111111111", "on my way")]
    assert matrix.notifications and matrix.notifications[0].startswith("✅")


def test_handle_send_sms_success():
    matrix, huawei = FakeMatrix(), FakeHuawei()
    handle(make_cfg(), huawei, matrix, FakeStore(), "!sms +33612345678 Hello")
    assert huawei.sent == [("+33612345678", "Hello")]
    assert matrix.notifications[0].startswith("✅")


def test_handle_send_sms_unexpected_response():
    matrix, huawei = FakeMatrix(), FakeHuawei()
    huawei.send_result = "ERROR"
    handle(make_cfg(), huawei, matrix, FakeStore(), "!sms +33612345678 Hello")
    assert matrix.notifications[0].startswith("⚠️")


def test_handle_send_sms_failure_notifies():
    matrix, huawei = FakeMatrix(), FakeHuawei()
    huawei.send_error = RuntimeError("radio off")
    handle(make_cfg(), huawei, matrix, FakeStore(), "!sms +33612345678 Hello")
    assert huawei.sent == []
    assert matrix.notifications[0].startswith("❌")
