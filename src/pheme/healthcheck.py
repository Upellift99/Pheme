"""Docker healthcheck: healthy iff the CPE answers ``sms_count()``."""

from __future__ import annotations

import os
import sys

from .huawei_client import HuaweiClient


def main() -> int:
    host = os.environ.get("HUAWEI_HOST", "192.168.8.1")
    user = os.environ.get("HUAWEI_USER", "admin")
    password = os.environ.get("HUAWEI_PASSWORD")
    if not password:
        print("UNHEALTHY: HUAWEI_PASSWORD not set", file=sys.stderr)
        return 1
    try:
        counts = HuaweiClient(host, user, password).sms_count()
    except Exception as exc:  # noqa: BLE001
        print(f"UNHEALTHY: {exc}", file=sys.stderr)
        return 1
    print(f"OK: CPE reachable, sms_count={counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
