"""Configuration loaded entirely from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing or invalid."""


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"Invalid boolean for {name}: {raw!r}")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid integer for {name}: {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    huawei_host: str
    huawei_user: str
    huawei_password: str
    matrix_homeserver: str
    matrix_token: str
    matrix_user_id: str
    matrix_room_id: str
    poll_interval: int
    state_db: str
    mark_as_read: bool
    delete_after_relay: bool
    allow_outbound: bool
    log_level: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            huawei_host=os.environ.get("HUAWEI_HOST", "192.168.8.1"),
            huawei_user=os.environ.get("HUAWEI_USER", "admin"),
            huawei_password=_required("HUAWEI_PASSWORD"),
            matrix_homeserver=_required("MATRIX_HOMESERVER").rstrip("/"),
            matrix_token=_required("MATRIX_TOKEN"),
            matrix_user_id=_required("MATRIX_USER_ID"),
            matrix_room_id=_required("MATRIX_ROOM_ID"),
            poll_interval=_int("POLL_INTERVAL", 60),
            state_db=os.environ.get("STATE_DB", "/data/state.db"),
            mark_as_read=_bool("MARK_AS_READ", False),
            delete_after_relay=_bool("DELETE_AFTER_RELAY", False),
            allow_outbound=_bool("ALLOW_OUTBOUND", True),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
