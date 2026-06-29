from pheme.huawei_client import estimate_segments, normalize_messages


def _msg(index, content="hi", smstat="0", phone="+33612345678"):
    return {
        "Index": str(index),
        "Phone": phone,
        "Content": content,
        "Date": "2026-06-30 10:00:00",
        "Smstat": smstat,
    }


def test_single_message_is_a_dict_not_a_list():
    box = {"Count": "1", "Messages": {"Message": _msg(40001)}}
    messages = normalize_messages(box)
    assert len(messages) == 1
    assert messages[0].index == 40001
    assert messages[0].unread is True


def test_multiple_messages_is_a_list():
    box = {"Count": "2", "Messages": {"Message": [_msg(2), _msg(1)]}}
    messages = normalize_messages(box)
    assert {m.index for m in messages} == {1, 2}


def test_empty_inbox_string():
    assert normalize_messages({"Count": "0", "Messages": ""}) == []


def test_empty_inbox_none():
    assert normalize_messages({"Count": "0", "Messages": None}) == []


def test_read_flag_is_parsed():
    box = {"Count": "1", "Messages": {"Message": _msg(7, smstat="1")}}
    assert normalize_messages(box)[0].unread is False


def test_segments_gsm7_boundaries():
    assert estimate_segments("a" * 160) == 1
    assert estimate_segments("a" * 161) == 2


def test_segments_non_gsm_uses_ucs2():
    # Emoji forces UCS-2 encoding: 70 chars per single segment, then 67.
    assert estimate_segments("😀" * 70) == 1
    assert estimate_segments("😀" * 71) == 2
