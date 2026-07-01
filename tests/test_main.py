import asyncio
from types import SimpleNamespace

import pytest

from pheme import __main__ as main
from pheme.config import Config


def make_cfg():
    return Config(
        huawei_host="192.168.8.1",
        huawei_user="admin",
        huawei_password="pw",
        matrix_homeserver="https://matrix.example.org",
        matrix_token="tok",
        matrix_user_id="@phemebot:example.org",
        matrix_room_id="!room:example.org",
        poll_interval=60,
        state_db=":memory:",
        mark_as_read=False,
        delete_after_relay=False,
        allow_outbound=True,
        log_level="INFO",
    )


class FakeMatrix:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


class FakeStore:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def wire(monkeypatch, cfg, matrix, store, loop_impl):
    monkeypatch.setattr(main, "setup_logging", lambda level: None)
    monkeypatch.setattr(main, "Config", SimpleNamespace(from_env=lambda: cfg))
    monkeypatch.setattr(main, "Store", lambda db: store)
    monkeypatch.setattr(main, "HuaweiClient", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(main, "MatrixClient", lambda *a, **k: matrix)
    monkeypatch.setattr(main, "inbound_loop", loop_impl)
    monkeypatch.setattr(main, "outbound_loop", loop_impl)


def test_run_wires_components_and_closes_on_exit(monkeypatch):
    matrix, store = FakeMatrix(), FakeStore()

    async def noop_loop(*args):
        return None

    wire(monkeypatch, make_cfg(), matrix, store, noop_loop)

    asyncio.run(main.run())

    assert matrix.closed is True
    assert store.closed is True


def test_run_closes_resources_even_on_loop_error(monkeypatch):
    matrix, store = FakeMatrix(), FakeStore()

    async def boom_loop(*args):
        raise RuntimeError("loop crashed")

    wire(monkeypatch, make_cfg(), matrix, store, boom_loop)

    with pytest.raises(RuntimeError, match="loop crashed"):
        asyncio.run(main.run())

    assert matrix.closed is True
    assert store.closed is True


def test_main_runs_the_coroutine(monkeypatch):
    calls = []

    def fake_run(coro):
        coro.close()  # avoid un-awaited coroutine warning
        calls.append(True)

    monkeypatch.setattr(main.asyncio, "run", fake_run)
    main.main()
    assert calls == [True]


def test_main_swallows_keyboard_interrupt(monkeypatch):
    def fake_run(coro):
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(main.asyncio, "run", fake_run)
    # Must not propagate — a Ctrl-C is a clean shutdown.
    main.main()
