from pheme.store import Store


def test_dedup(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    assert store.is_relayed(5) is False
    store.mark_relayed(5, "+33612345678", "2026-06-30 10:00:00")
    assert store.is_relayed(5) is True
    # Marking again is idempotent.
    store.mark_relayed(5, "+33612345678", "2026-06-30 10:00:00")
    assert store.is_relayed(5) is True


def test_dedup_survives_reopen(tmp_path):
    path = str(tmp_path / "state.db")
    store = Store(path)
    store.mark_relayed(42, "+33600000000", "2026-06-30 10:00:00")
    store.close()
    # A container restart must not re-relay already-seen messages.
    reopened = Store(path)
    assert reopened.is_relayed(42) is True


def test_last_inbound_phone_tracks_latest(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    assert store.last_inbound_phone() is None
    store.mark_relayed(1, "+111", "d1")
    store.mark_relayed(2, "+222", "d2")
    assert store.last_inbound_phone() == "+222"


def test_sync_token_roundtrip(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    assert store.get_sync_token() is None
    store.set_sync_token("s_abc_123")
    assert store.get_sync_token() == "s_abc_123"
    store.set_sync_token("s_def_456")
    assert store.get_sync_token() == "s_def_456"
