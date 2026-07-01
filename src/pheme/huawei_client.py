"""Thin wrapper over ``huawei-lte-api`` for the HiLink SMS endpoints.

Every operation opens a fresh authenticated session (Huawei CPEs only allow a
limited number of concurrent web sessions, and a stale token raises ``125003``).
The pure-Python helpers (:func:`normalize_messages`, :func:`estimate_segments`)
are kept free of network access so they can be unit-tested in isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import quote

from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection
from huawei_lte_api.enums.sms import BoxTypeEnum, SortTypeEnum

log = logging.getLogger("pheme.huawei")

# GSM 03.38 7-bit default alphabet. Characters in the basic set cost 1 unit;
# characters in the extension table cost 2 units (they are escaped on the wire).
_GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = "\f^{}\\[~]|€"
GSM7_SINGLE = set(_GSM7_BASIC)
GSM7_EXT = set(_GSM7_EXT)


@dataclass(frozen=True)
class Sms:
    index: int
    phone: str
    content: str
    date: str
    unread: bool


def normalize_messages(box: dict) -> list[Sms]:
    """Normalise a ``get_sms_list`` response into a list of :class:`Sms`.

    Handles the HiLink quirks: ``Messages`` may be an empty string/None when the
    inbox is empty, and ``Messages.Message`` is a single dict (not a list) when
    there is exactly one message.
    """
    messages = box.get("Messages")
    if not messages:
        return []
    raw = messages.get("Message")
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]

    result: list[Sms] = []
    for m in raw:
        result.append(
            Sms(
                index=int(m["Index"]),
                phone=m.get("Phone") or "",
                content=m.get("Content") or "",
                date=m.get("Date") or "",
                unread=str(m.get("Smstat")) == "0",
            )
        )
    return result


def estimate_segments(text: str) -> int:
    """Estimate how many SMS segments ``text`` will be split into."""
    if not text:
        return 1
    if all(c in GSM7_SINGLE or c in GSM7_EXT for c in text):
        units = sum(2 if c in GSM7_EXT else 1 for c in text)
        return 1 if units <= 160 else -(-units // 153)
    # Non-GSM characters (accents outside the table, emoji, ...) force UCS-2.
    units = len(text)
    return 1 if units <= 70 else -(-units // 67)


class HuaweiClient:
    def __init__(self, host: str, user: str, password: str) -> None:
        self._url = f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}/"
        self.host = host

    @contextmanager
    def _client(self) -> Iterator[Client]:
        with Connection(self._url) as connection:
            yield Client(connection)

    def list_inbox(self) -> list[Sms]:
        with self._client() as client:
            box = client.sms.get_sms_list(
                box_type=BoxTypeEnum.LOCAL_INBOX, sort_type=SortTypeEnum.DATE
            )
        messages = normalize_messages(box)
        # Relay oldest first so the Matrix room preserves chronological order.
        messages.sort(key=lambda s: s.index)
        return messages

    def send_sms(self, recipient: str, text: str) -> str:
        with self._client() as client:
            return client.sms.send_sms([recipient], text)

    def finalize(self, read_indices: list[int], delete_indices: list[int]) -> None:
        """Mark relayed messages as read and/or delete them, in one session."""
        if not read_indices and not delete_indices:
            return
        with self._client() as client:
            for index in read_indices:
                try:
                    client.sms.set_read(index)
                # best-effort, never fatal
                except Exception:  # noqa: BLE001
                    log.warning("set_read failed", extra={"extra_fields": {"index": index}})
            for index in delete_indices:
                try:
                    client.sms.delete_sms(index)
                # best-effort, never fatal
                except Exception:  # noqa: BLE001
                    log.warning("delete_sms failed", extra={"extra_fields": {"index": index}})

    def sms_count(self) -> dict:
        with self._client() as client:
            return client.sms.sms_count()
