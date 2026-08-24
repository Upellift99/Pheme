import json
import logging

from pheme.logging_config import JsonFormatter, setup_logging


def _record(**kwargs):
    defaults = dict(
        name="pheme.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    defaults.update(kwargs)
    return logging.LogRecord(func=None, **defaults)


def test_format_basic_fields():
    line = JsonFormatter().format(_record())
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "pheme.test"
    assert payload["msg"] == "hello world"
    assert "ts" in payload
    assert "exc" not in payload


def test_format_merges_extra_fields():
    record = _record()
    record.extra_fields = {"index": 7, "phone": "+33"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["index"] == 7
    assert payload["phone"] == "+33"


def test_format_ignores_non_dict_extra_fields():
    record = _record()
    record.extra_fields = "not-a-dict"
    payload = json.loads(JsonFormatter().format(record))
    assert "extra_fields" not in payload


def test_format_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record(exc_info=sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert "exc" in payload
    assert "ValueError" in payload["exc"]


def test_format_non_ascii_is_preserved():
    payload = json.loads(JsonFormatter().format(_record(msg="héllo", args=())))
    assert payload["msg"] == "héllo"


def test_setup_logging_installs_single_json_handler():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    try:
        setup_logging("debug")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.DEBUG
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def test_setup_logging_never_lets_huawei_lte_api_log_at_debug():
    # huawei-lte-api 2.x logs the CPE password at DEBUG; LOG_LEVEL=debug must
    # not turn that on.
    root = logging.getLogger()
    vendor = logging.getLogger("huawei_lte_api")
    original_handlers = root.handlers[:]
    original_level = root.level
    original_vendor_level = vendor.level
    try:
        setup_logging("debug")
        assert root.level == logging.DEBUG
        assert vendor.level == logging.INFO
        assert not vendor.isEnabledFor(logging.DEBUG)
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
        vendor.setLevel(original_vendor_level)
