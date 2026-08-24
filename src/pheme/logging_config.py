"""Structured JSON logging to stdout."""

from __future__ import annotations

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """Render each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # huawei-lte-api 2.x logs the CPE credentials in clear text at DEBUG
    # (Connection.py: `_LOGGER.debug("Password: %s", password)`). LOG_LEVEL is
    # operator-facing and DEBUG is exactly what you reach for when the CPE stops
    # answering, so floor that logger at INFO rather than leak HUAWEI_PASSWORD
    # into stdout — and from there into the container logs.
    logging.getLogger("huawei_lte_api").setLevel(logging.INFO)
