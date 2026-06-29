"""Matrix Client-Server API access: send messages and long-poll /sync."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

import httpx

from .huawei_client import Sms

log = logging.getLogger("pheme.matrix")


@dataclass(frozen=True)
class MatrixMessage:
    event_id: str
    sender: str
    body: str


class MatrixClient:
    def __init__(
        self,
        homeserver: str,
        token: str,
        room_id: str,
        user_id: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = homeserver.rstrip("/")
        self._room = room_id
        self._user = user_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        # Restrict /sync to our room and to text messages, keeping payloads small.
        self._filter = json.dumps(
            {
                "room": {
                    "rooms": [room_id],
                    "timeline": {"types": ["m.room.message"], "limit": 50},
                    "ephemeral": {"types": []},
                    "state": {"types": [], "lazy_load_members": True},
                },
                "presence": {"types": []},
                "account_data": {"types": []},
            }
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- sending -------------------------------------------------------

    async def _send(
        self, body: str, formatted: str | None = None, txn_id: str | None = None
    ) -> str | None:
        txn_id = txn_id or f"pheme-{uuid.uuid4().hex}"
        content: dict[str, str] = {"msgtype": "m.text", "body": body}
        if formatted is not None:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = formatted
        url = (
            f"{self._base}/_matrix/client/v3/rooms/{quote(self._room)}"
            f"/send/m.room.message/{quote(txn_id)}"
        )
        response = await self._http.put(url, headers=self._headers, json=content)
        response.raise_for_status()
        return response.json().get("event_id")

    async def relay_sms(self, sms: Sms) -> str | None:
        """Push an inbound SMS into the room (idempotent via the SMS Index)."""
        sender = sms.phone or "unknown"
        body = f"SMS from {sender} ({sms.date}):\n{sms.content}"
        formatted = (
            f"<strong>SMS from {escape(sender)}</strong> "
            f"<em>{escape(sms.date)}</em><br/>{escape(sms.content)}"
        )
        return await self._send(body, formatted, txn_id=f"pheme-sms-{sms.index}")

    async def notify(self, text: str) -> str | None:
        """Post a short confirmation/usage message into the room."""
        return await self._send(text)

    # --- receiving -----------------------------------------------------

    async def initial_sync_token(self) -> str:
        """Return the current ``next_batch`` without backfilling history."""
        url = f"{self._base}/_matrix/client/v3/sync"
        response = await self._http.get(
            url,
            headers=self._headers,
            params={"timeout": 0, "filter": self._filter},
        )
        response.raise_for_status()
        return response.json()["next_batch"]

    async def sync(self, since: str, timeout_ms: int = 30000) -> tuple[str, list[MatrixMessage]]:
        url = f"{self._base}/_matrix/client/v3/sync"
        response = await self._http.get(
            url,
            headers=self._headers,
            params={"timeout": timeout_ms, "since": since, "filter": self._filter},
            timeout=httpx.Timeout(timeout_ms / 1000 + 30),
        )
        response.raise_for_status()
        data = response.json()
        return data["next_batch"], self._extract_room_messages(data)

    def _extract_room_messages(self, data: dict) -> list[MatrixMessage]:
        out: list[MatrixMessage] = []
        room = data.get("rooms", {}).get("join", {}).get(self._room)
        if not room:
            return out
        for event in room.get("timeline", {}).get("events", []):
            if event.get("type") != "m.room.message":
                continue
            content = event.get("content", {})
            if content.get("msgtype") != "m.text":
                continue
            out.append(
                MatrixMessage(
                    event_id=event.get("event_id", ""),
                    sender=event.get("sender", ""),
                    body=content.get("body", ""),
                )
            )
        return out
