"""SQLite-backed state: SMS dedup, last inbound sender, Matrix sync token."""

from __future__ import annotations

import datetime
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS relayed_sms (
    sms_index  INTEGER PRIMARY KEY,
    phone      TEXT,
    sms_date   TEXT,
    relayed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_LAST_INBOUND_PHONE = "last_inbound_phone"
_SYNC_TOKEN = "sync_token"


def _utcnow() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


class Store:
    """Thread-safe wrapper over a single SQLite connection.

    Both async loops call into this from worker threads (via ``asyncio.to_thread``
    for blocking Huawei calls) and from the event loop, so every access is guarded
    by a lock and the connection is opened with ``check_same_thread=False``.
    """

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    # --- inbound dedup -------------------------------------------------

    def is_relayed(self, index: int) -> bool:
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM relayed_sms WHERE sms_index = ?", (index,))
            return cur.fetchone() is not None

    def mark_relayed(self, index: int, phone: str, date: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO relayed_sms (sms_index, phone, sms_date, relayed_at) "
                "VALUES (?, ?, ?, ?)",
                (index, phone, date, _utcnow()),
            )
            self._set_meta(_LAST_INBOUND_PHONE, phone)

    def last_inbound_phone(self) -> str | None:
        return self.get_meta(_LAST_INBOUND_PHONE)

    # --- outbound sync token -------------------------------------------

    def get_sync_token(self) -> str | None:
        return self.get_meta(_SYNC_TOKEN)

    def set_sync_token(self, token: str) -> None:
        with self._lock, self._conn:
            self._set_meta(_SYNC_TOKEN, token)

    # --- generic meta helpers ------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            cur = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        # Caller must already hold the lock and an open transaction.
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
