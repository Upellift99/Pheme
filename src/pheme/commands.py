"""Parse outbound SMS commands typed into the Matrix room.

Grammar:
    !sms <number> <text>   -> send <text> to <number>
    !reply <text>          -> reply to the most recent inbound sender

Anything else returns either a ``Usage`` hint (malformed ``!`` command) or
``None`` (own message, or a plain non-prefixed message that should be ignored).
"""

from __future__ import annotations

from dataclasses import dataclass

USAGE = "Usage: !sms <number> <text>   |   !reply <text>"


@dataclass(frozen=True)
class SendSms:
    number: str
    text: str


@dataclass(frozen=True)
class ReplyLast:
    text: str


@dataclass(frozen=True)
class Usage:
    message: str


Command = SendSms | ReplyLast | Usage


def _valid_number(number: str) -> bool:
    core = number[1:] if number.startswith("+") else number
    return core.isdigit() and 3 <= len(core) <= 15


def parse_command(body: str, sender: str, bot_user_id: str) -> Command | None:
    """Return the parsed command, a usage hint, or None to ignore the message."""
    if sender == bot_user_id:
        # Never act on our own messages — avoids feedback loops.
        return None
    if not body:
        return None

    text = body.strip()
    if not text.startswith("!"):
        # Plain chatter: humans can talk in the room without triggering sends.
        return None

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "!sms":
        bits = rest.split(maxsplit=1)
        if len(bits) < 2 or not bits[1].strip():
            return Usage(USAGE)
        number = bits[0]
        if not _valid_number(number):
            return Usage(f"Invalid number {number!r}. {USAGE}")
        return SendSms(number=number, text=bits[1].strip())

    if cmd == "!reply":
        if not rest:
            return Usage(USAGE)
        return ReplyLast(text=rest)

    return Usage(USAGE)
