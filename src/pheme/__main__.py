"""Entrypoint: load config, wire components, run both loops concurrently."""

from __future__ import annotations

import asyncio
import logging
import os

from .config import Config
from .huawei_client import HuaweiClient
from .logging_config import setup_logging
from .loops import inbound_loop, outbound_loop
from .matrix_client import MatrixClient
from .store import Store

log = logging.getLogger("pheme")


async def run() -> None:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    cfg = Config.from_env()
    setup_logging(cfg.log_level)

    log.info(
        "starting pheme",
        extra={
            "extra_fields": {
                "huawei_host": cfg.huawei_host,
                "room": cfg.matrix_room_id,
                "poll_interval": cfg.poll_interval,
                "allow_outbound": cfg.allow_outbound,
                "mark_as_read": cfg.mark_as_read,
                "delete_after_relay": cfg.delete_after_relay,
            }
        },
    )

    store = Store(cfg.state_db)
    huawei = HuaweiClient(cfg.huawei_host, cfg.huawei_user, cfg.huawei_password)
    matrix = MatrixClient(
        cfg.matrix_homeserver, cfg.matrix_token, cfg.matrix_room_id, cfg.matrix_user_id
    )

    try:
        await asyncio.gather(
            inbound_loop(cfg, huawei, matrix, store),
            outbound_loop(cfg, huawei, matrix, store),
        )
    finally:
        await matrix.aclose()
        store.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
