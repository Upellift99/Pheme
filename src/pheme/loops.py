"""The two independent async loops and their shared backoff helper."""

from __future__ import annotations

import asyncio
import logging

from .commands import ReplyLast, SendSms, Usage, parse_command
from .config import Config
from .huawei_client import HuaweiClient, estimate_segments
from .matrix_client import MatrixClient, MatrixMessage
from .store import Store

log = logging.getLogger("pheme.loops")


class Backoff:
    """Exponential backoff with a ceiling, reset after a successful cycle."""

    def __init__(self, base: float = 5.0, factor: float = 2.0, maximum: float = 300.0) -> None:
        self._base = base
        self._factor = factor
        self._max = maximum
        self._n = 0

    def reset(self) -> None:
        self._n = 0

    def next(self) -> float:
        delay = min(self._max, self._base * (self._factor**self._n))
        self._n += 1
        return delay


async def _notify_safe(matrix: MatrixClient, text: str) -> None:
    """Post to the room, swallowing Matrix errors.

    Used from health alerting only: a homeserver outage must never turn into a
    second failure on top of the one we are trying to report.
    """
    try:
        await matrix.notify(text)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("failed to post health alert to matrix")


async def inbound_loop(
    cfg: Config, huawei: HuaweiClient, matrix: MatrixClient, store: Store
) -> None:
    """Poll the CPE inbox and relay new SMS to Matrix.

    Inbound failures are otherwise invisible — nothing is posted to the room when
    the CPE is unreachable, so a dead bridge looks exactly like a quiet one. After
    ``ALERT_AFTER_FAILURES`` consecutive failed cycles the room gets one warning,
    and one all-clear once polling recovers.
    """
    backoff = Backoff()
    failures = 0
    alerted = False
    while True:
        try:
            messages = await asyncio.to_thread(huawei.list_inbox)
            relayed = []
            for sms in messages:
                if store.is_relayed(sms.index):
                    continue
                await matrix.relay_sms(sms)
                store.mark_relayed(sms.index, sms.phone, sms.date)
                relayed.append(sms)
                log.info(
                    "relayed inbound sms",
                    extra={
                        "extra_fields": {
                            "index": sms.index,
                            "phone": sms.phone,
                            "segments": estimate_segments(sms.content),
                        }
                    },
                )

            if relayed and (cfg.mark_as_read or cfg.delete_after_relay):
                read_indices = [s.index for s in relayed if cfg.mark_as_read and s.unread]
                delete_indices = [s.index for s in relayed if cfg.delete_after_relay]
                await asyncio.to_thread(huawei.finalize, read_indices, delete_indices)

            backoff.reset()
            if alerted:
                await _notify_safe(
                    matrix,
                    f"✅ CPE reachable again — inbound relay resumed after {failures} "
                    "failed poll(s).",
                )
                alerted = False
            failures = 0
            await asyncio.sleep(cfg.poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad cycle must never kill the loop
            failures += 1
            delay = backoff.next()
            log.exception(
                "inbound loop error; retrying",
                extra={"extra_fields": {"retry_in": delay, "consecutive_failures": failures}},
            )
            if not alerted and 0 < cfg.alert_after_failures <= failures:
                alerted = True
                await _notify_safe(
                    matrix,
                    f"⚠️ Inbound relay down: {failures} consecutive poll failures. "
                    f"No SMS is being relayed. Last error: "
                    f"{type(exc).__name__}: {str(exc)[:200] or '(no detail)'}",
                )
            await asyncio.sleep(delay)


async def outbound_loop(
    cfg: Config, huawei: HuaweiClient, matrix: MatrixClient, store: Store
) -> None:
    """Long-poll Matrix /sync and send commanded SMS through the CPE."""
    if not cfg.allow_outbound:
        log.info("outbound disabled (ALLOW_OUTBOUND=false)")
        return

    backoff = Backoff()
    since = store.get_sync_token()
    while since is None:
        try:
            since = await matrix.initial_sync_token()
            store.set_sync_token(since)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            delay = backoff.next()
            log.exception(
                "failed to obtain initial sync token; retrying",
                extra={"extra_fields": {"retry_in": delay}},
            )
            await asyncio.sleep(delay)
    backoff.reset()

    while True:
        try:
            next_batch, messages = await matrix.sync(since)
            for message in messages:
                await _handle_message(cfg, huawei, matrix, store, message)
            since = next_batch
            store.set_sync_token(since)
            backoff.reset()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            delay = backoff.next()
            log.exception(
                "outbound loop error; retrying", extra={"extra_fields": {"retry_in": delay}}
            )
            await asyncio.sleep(delay)


async def _handle_message(
    cfg: Config,
    huawei: HuaweiClient,
    matrix: MatrixClient,
    store: Store,
    message: MatrixMessage,
) -> None:
    command = parse_command(message.body, message.sender, cfg.matrix_user_id)
    if command is None:
        return
    if isinstance(command, Usage):
        await matrix.notify(command.message)
        return

    if isinstance(command, ReplyLast):
        number = store.last_inbound_phone()
        if not number:
            await matrix.notify("No previous inbound sender to reply to.")
            return
        text = command.text
    else:
        assert isinstance(command, SendSms)
        number = command.number
        text = command.text

    segments = estimate_segments(text)
    try:
        result = await asyncio.to_thread(huawei.send_sms, number, text)
    except Exception:  # noqa: BLE001
        log.exception("failed to send sms", extra={"extra_fields": {"number": number}})
        await matrix.notify(f"❌ Failed to send SMS to {number}.")
        return

    if str(result).upper() == "OK":
        log.info(
            "sent outbound sms",
            extra={"extra_fields": {"number": number, "segments": segments}},
        )
        await matrix.notify(
            f"✅ SMS queued to {number} ({segments} segment(s)). "
            "Note: accepted by the CPE, not confirmed delivered."
        )
    else:
        await matrix.notify(f"⚠️ Unexpected response sending to {number}: {result}")
