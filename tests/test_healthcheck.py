import pytest

from pheme import healthcheck


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("HUAWEI_HOST", "HUAWEI_USER", "HUAWEI_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_missing_password_is_unhealthy(clean_env, capsys):
    assert healthcheck.main() == 1
    assert "HUAWEI_PASSWORD not set" in capsys.readouterr().err


def test_ok_when_cpe_answers(clean_env, capsys, monkeypatch):
    clean_env.setenv("HUAWEI_PASSWORD", "secret")
    captured_args = {}

    class FakeClient:
        def __init__(self, host, user, password):
            captured_args.update(host=host, user=user, password=password)

        def sms_count(self):
            return {"LocalInbox": "3"}

    monkeypatch.setattr(healthcheck, "HuaweiClient", FakeClient)

    assert healthcheck.main() == 0
    out = capsys.readouterr().out
    assert "OK: CPE reachable" in out
    assert "LocalInbox" in out
    # Falls back to the documented defaults when host/user are unset.
    assert captured_args == {"host": "192.168.8.1", "user": "admin", "password": "secret"}


def test_uses_env_host_and_user(clean_env, monkeypatch):
    clean_env.setenv("HUAWEI_PASSWORD", "secret")
    clean_env.setenv("HUAWEI_HOST", "10.0.0.2")
    clean_env.setenv("HUAWEI_USER", "root")
    captured_args = {}

    class FakeClient:
        def __init__(self, host, user, password):
            captured_args.update(host=host, user=user)

        def sms_count(self):
            return {}

    monkeypatch.setattr(healthcheck, "HuaweiClient", FakeClient)

    assert healthcheck.main() == 0
    assert captured_args == {"host": "10.0.0.2", "user": "root"}


def test_unhealthy_when_client_raises(clean_env, capsys, monkeypatch):
    clean_env.setenv("HUAWEI_PASSWORD", "secret")

    class FakeClient:
        def __init__(self, *args):
            pass

        def sms_count(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(healthcheck, "HuaweiClient", FakeClient)

    assert healthcheck.main() == 1
    assert "UNHEALTHY: connection refused" in capsys.readouterr().err
