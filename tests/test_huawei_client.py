import pytest

from pheme import huawei_client
from pheme.huawei_client import HuaweiClient, normalize_messages


class FakeSmsApi:
    def __init__(self, inbox_box=None, send_result="OK", counts=None):
        self.inbox_box = inbox_box or {}
        self.send_result = send_result
        self.counts = counts or {}
        self.read = []
        self.deleted = []
        self.sent = []
        self.set_read_error_on = set()
        self.delete_error_on = set()

    def get_sms_list(self, box_type=None, sort_type=None):
        return self.inbox_box

    def set_read(self, index):
        if index in self.set_read_error_on:
            raise RuntimeError("set_read boom")
        self.read.append(index)

    def delete_sms(self, index):
        if index in self.delete_error_on:
            raise RuntimeError("delete boom")
        self.deleted.append(index)

    def send_sms(self, recipients, text):
        self.sent.append((recipients, text))
        return self.send_result

    def sms_count(self):
        return self.counts


class FakeConnection:
    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def patch_network(monkeypatch):
    def install(sms_api):
        monkeypatch.setattr(huawei_client, "Connection", FakeConnection)
        monkeypatch.setattr(
            huawei_client, "Client", lambda connection: type("C", (), {"sms": sms_api})()
        )
        return sms_api

    return install


def _client():
    return HuaweiClient("192.168.8.1", "admin", "pw")


# --- __init__ ----------------------------------------------------------


def test_url_encodes_credentials():
    client = HuaweiClient("192.168.8.1", "ad min", "p@ss/w")
    assert client.host == "192.168.8.1"
    assert "ad%20min" in client._url
    assert "p%40ss%2Fw" in client._url


# --- list_inbox --------------------------------------------------------


def test_list_inbox_returns_messages_sorted_by_index(patch_network):
    box = {
        "Messages": {
            "Message": [
                {"Index": "2", "Phone": "+331", "Content": "second", "Date": "d", "Smstat": "1"},
                {"Index": "1", "Phone": "+332", "Content": "first", "Date": "d", "Smstat": "0"},
            ]
        }
    }
    patch_network(FakeSmsApi(inbox_box=box))
    messages = _client().list_inbox()
    assert [m.index for m in messages] == [1, 2]
    assert messages[0].content == "first"


# --- send_sms ----------------------------------------------------------


def test_send_sms_wraps_recipient_in_list(patch_network):
    api = patch_network(FakeSmsApi(send_result="OK"))
    assert _client().send_sms("+33612345678", "hi") == "OK"
    assert api.sent == [(["+33612345678"], "hi")]


# --- finalize ----------------------------------------------------------


def test_finalize_marks_read_and_deletes(patch_network):
    api = patch_network(FakeSmsApi())
    _client().finalize([1, 2], [3])
    assert api.read == [1, 2]
    assert api.deleted == [3]


def test_finalize_noop_when_both_empty(patch_network):
    api = patch_network(FakeSmsApi())
    _client().finalize([], [])
    assert api.read == []
    assert api.deleted == []


def test_finalize_is_best_effort_on_errors(patch_network):
    api = FakeSmsApi()
    api.set_read_error_on = {1}
    api.delete_error_on = {3}
    patch_network(api)

    # A failure on one index must not abort the rest of the batch.
    _client().finalize([1, 2], [3, 4])

    assert api.read == [2]
    assert api.deleted == [4]


# --- sms_count ---------------------------------------------------------


def test_sms_count_returns_counts(patch_network):
    patch_network(FakeSmsApi(counts={"LocalInbox": "5"}))
    assert _client().sms_count() == {"LocalInbox": "5"}


# --- normalize_messages extra branches --------------------------------


def test_estimate_segments_empty_text():
    assert huawei_client.estimate_segments("") == 1


def test_normalize_returns_empty_when_message_is_none():
    assert normalize_messages({"Messages": {"Message": None}}) == []


def test_normalize_defaults_missing_fields():
    box = {"Messages": {"Message": {"Index": "5"}}}
    message = normalize_messages(box)[0]
    assert message.index == 5
    assert message.phone == ""
    assert message.content == ""
    assert message.date == ""
    assert message.unread is False  # Smstat absent -> treated as read
