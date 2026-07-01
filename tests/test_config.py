import pytest

from pheme.config import Config, ConfigError, _bool, _int, _required

REQUIRED_ENV = {
    "HUAWEI_PASSWORD": "secret",
    "MATRIX_HOMESERVER": "https://matrix.example.org",
    "MATRIX_TOKEN": "tok",
    "MATRIX_USER_ID": "@phemebot:example.org",
    "MATRIX_ROOM_ID": "!room:example.org",
}


@pytest.fixture
def clean_env(monkeypatch):
    """Start from an environment with none of the config variables set."""
    for name in (
        *REQUIRED_ENV,
        "HUAWEI_HOST",
        "HUAWEI_USER",
        "POLL_INTERVAL",
        "STATE_DB",
        "MARK_AS_READ",
        "DELETE_AFTER_RELAY",
        "ALLOW_OUTBOUND",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_required_returns_value(clean_env):
    clean_env.setenv("HUAWEI_PASSWORD", "hunter2")
    assert _required("HUAWEI_PASSWORD") == "hunter2"


def test_required_missing_raises(clean_env):
    with pytest.raises(ConfigError, match="Missing required environment variable: X"):
        _required("X")


def test_required_empty_raises(clean_env):
    clean_env.setenv("X", "")
    with pytest.raises(ConfigError):
        _required("X")


def test_bool_default_when_unset(clean_env):
    assert _bool("FLAG", default=True) is True
    assert _bool("FLAG", default=False) is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " On "])
def test_bool_truthy(clean_env, raw):
    clean_env.setenv("FLAG", raw)
    assert _bool("FLAG", default=False) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", ""])
def test_bool_falsy(clean_env, raw):
    clean_env.setenv("FLAG", raw)
    assert _bool("FLAG", default=True) is False


def test_bool_invalid_raises(clean_env):
    clean_env.setenv("FLAG", "maybe")
    with pytest.raises(ConfigError, match="Invalid boolean for FLAG"):
        _bool("FLAG", default=False)


def test_int_default_when_unset(clean_env):
    assert _int("NUM", default=60) == 60


def test_int_parses_value(clean_env):
    clean_env.setenv("NUM", "120")
    assert _int("NUM", default=60) == 120


def test_int_invalid_raises(clean_env):
    clean_env.setenv("NUM", "abc")
    with pytest.raises(ConfigError, match="Invalid integer for NUM"):
        _int("NUM", default=60)


def test_from_env_defaults(clean_env):
    for name, value in REQUIRED_ENV.items():
        clean_env.setenv(name, value)

    cfg = Config.from_env()

    assert cfg.huawei_host == "192.168.8.1"
    assert cfg.huawei_user == "admin"
    assert cfg.huawei_password == "secret"
    assert cfg.matrix_homeserver == "https://matrix.example.org"
    assert cfg.poll_interval == 60
    assert cfg.state_db == "/data/state.db"
    assert cfg.mark_as_read is False
    assert cfg.delete_after_relay is False
    assert cfg.allow_outbound is True
    assert cfg.log_level == "INFO"


def test_from_env_overrides_and_strips_homeserver_slash(clean_env):
    for name, value in REQUIRED_ENV.items():
        clean_env.setenv(name, value)
    clean_env.setenv("MATRIX_HOMESERVER", "https://matrix.example.org/")
    clean_env.setenv("HUAWEI_HOST", "10.0.0.1")
    clean_env.setenv("HUAWEI_USER", "root")
    clean_env.setenv("POLL_INTERVAL", "30")
    clean_env.setenv("STATE_DB", "/tmp/state.db")
    clean_env.setenv("MARK_AS_READ", "yes")
    clean_env.setenv("DELETE_AFTER_RELAY", "1")
    clean_env.setenv("ALLOW_OUTBOUND", "no")
    clean_env.setenv("LOG_LEVEL", "DEBUG")

    cfg = Config.from_env()

    assert cfg.matrix_homeserver == "https://matrix.example.org"
    assert cfg.huawei_host == "10.0.0.1"
    assert cfg.huawei_user == "root"
    assert cfg.poll_interval == 30
    assert cfg.state_db == "/tmp/state.db"
    assert cfg.mark_as_read is True
    assert cfg.delete_after_relay is True
    assert cfg.allow_outbound is False
    assert cfg.log_level == "DEBUG"


def test_from_env_missing_required_raises(clean_env):
    # Only set some of the required variables.
    clean_env.setenv("HUAWEI_PASSWORD", "secret")
    with pytest.raises(ConfigError, match="MATRIX_HOMESERVER"):
        Config.from_env()
