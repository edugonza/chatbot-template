import pytest

from src.config import ConfigError, Settings

REQUIRED_VARS = {
    "MATRIX_USER_ID": "@bot:matrix.org",
    "MATRIX_ACCESS_TOKEN": "token123",
    "MATRIX_DEVICE_ID": "DEVICEID",
    "GEMINI_API_KEY": "gemini-key",
}


def _set_required(monkeypatch, **overrides):
    values = {**REQUIRED_VARS, **overrides}
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _clear_optional(monkeypatch):
    for key in (
        "MATRIX_HOMESERVER",
        "MATRIX_STORE_PATH",
        "MATRIX_STORE_PASSPHRASE",
        "MATRIX_ALLOWED_USERS",
        "MATRIX_ALLOWED_ROOMS",
        "GEMINI_MODEL",
        "BOT_HISTORY_LENGTH",
        "BOT_HISTORY_BATCH",
        "BOT_HISTORY_DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_missing_required_var_raises(monkeypatch):
    _clear_optional(monkeypatch)
    monkeypatch.delenv("MATRIX_USER_ID", raising=False)
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@you:matrix.org")

    with pytest.raises(ConfigError, match="MATRIX_USER_ID"):
        Settings.from_env()


def test_missing_allowlist_raises(monkeypatch):
    _clear_optional(monkeypatch)
    _set_required(monkeypatch)

    with pytest.raises(ConfigError, match="MATRIX_ALLOWED_USERS"):
        Settings.from_env()


def test_defaults_applied(monkeypatch):
    _clear_optional(monkeypatch)
    _set_required(monkeypatch)
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@you:matrix.org")

    settings = Settings.from_env()

    assert settings.matrix_homeserver == "https://matrix.org"
    assert settings.matrix_store_path == "/data/store"
    assert settings.matrix_store_passphrase is None
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.history_db_path == "/data/store/history.db"
    assert settings.history_context_turns == 200
    assert settings.history_context_batch == 50


def test_allowlist_parsing_trims_and_splits(monkeypatch):
    _clear_optional(monkeypatch)
    _set_required(monkeypatch)
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", " @a:matrix.org, @b:matrix.org ,")
    monkeypatch.setenv("MATRIX_ALLOWED_ROOMS", "!room:matrix.org")

    settings = Settings.from_env()

    assert settings.is_user_allowed("@a:matrix.org")
    assert settings.is_user_allowed("@b:matrix.org")
    assert not settings.is_user_allowed("@c:matrix.org")
    assert settings.is_room_allowed("!room:matrix.org")
