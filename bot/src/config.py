"""Environment-driven configuration for the bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _split_csv(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"required environment variable {name!r} is not set")
    return value


@dataclass(frozen=True)
class Settings:
    matrix_homeserver: str
    matrix_user_id: str
    matrix_access_token: str
    matrix_device_id: str
    matrix_store_path: str
    matrix_store_passphrase: str | None
    allowed_users: frozenset[str]
    allowed_rooms: frozenset[str]
    gemini_api_key: str
    gemini_model: str
    history_db_path: str = field(default="/data/store/history.db")
    history_context_turns: int = field(default=200)
    history_context_batch: int = field(default=50)

    def is_user_allowed(self, user_id: str) -> bool:
        return user_id in self.allowed_users

    def is_room_allowed(self, room_id: str) -> bool:
        return room_id in self.allowed_rooms

    @classmethod
    def from_env(cls) -> "Settings":
        allowed_users = _split_csv(os.environ.get("MATRIX_ALLOWED_USERS"))
        allowed_rooms = _split_csv(os.environ.get("MATRIX_ALLOWED_ROOMS"))
        if not allowed_users and not allowed_rooms:
            raise ConfigError(
                "at least one of MATRIX_ALLOWED_USERS or MATRIX_ALLOWED_ROOMS must be set"
            )

        return cls(
            matrix_homeserver=os.environ.get("MATRIX_HOMESERVER", "https://matrix.org"),
            matrix_user_id=_require("MATRIX_USER_ID"),
            matrix_access_token=_require("MATRIX_ACCESS_TOKEN"),
            matrix_device_id=_require("MATRIX_DEVICE_ID"),
            matrix_store_path=os.environ.get("MATRIX_STORE_PATH", "/data/store"),
            matrix_store_passphrase=os.environ.get("MATRIX_STORE_PASSPHRASE") or None,
            allowed_users=allowed_users,
            allowed_rooms=allowed_rooms,
            gemini_api_key=_require("GEMINI_API_KEY"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            history_db_path=os.environ.get("BOT_HISTORY_DB_PATH", "/data/store/history.db"),
            history_context_turns=int(os.environ.get("BOT_HISTORY_LENGTH", "200")),
            history_context_batch=int(os.environ.get("BOT_HISTORY_BATCH", "50")),
        )
