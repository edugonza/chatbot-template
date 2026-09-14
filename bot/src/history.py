"""Per-room conversation history, persisted to disk in SQLite.

Every turn is kept until a room is reset with `!reset`. What gets sent back to
the model on each call is a bounded window (`context_turns`), independent of
retention.

The window's start only advances in `context_batch`-sized jumps rather than
sliding by one turn per message. That keeps the prefix handed to the model
byte-identical across `context_batch` consecutive calls, which lets implicit
prefix caching actually hit instead of missing on every turn.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Turn:
    role: str  # "user" or "model"
    text: str


def _window_skip(count: int, context_turns: int, context_batch: int) -> int:
    excess = count - context_turns
    if excess <= 0:
        return 0
    return (excess // context_batch) * context_batch


class ConversationHistory:
    def __init__(self, db_path: str, context_turns: int, context_batch: int) -> None:
        self._db_path = db_path
        self._context_turns = context_turns
        self._context_batch = context_batch

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_turns_room_id ON turns(room_id, id)"
                )
                conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def get(self, room_id: str) -> list[Turn]:
        return await asyncio.to_thread(self._get_sync, room_id)

    async def append(self, room_id: str, role: str, text: str) -> None:
        await asyncio.to_thread(self._append_sync, room_id, role, text)

    async def clear(self, room_id: str) -> None:
        await asyncio.to_thread(self._clear_sync, room_id)

    def _get_sync(self, room_id: str) -> list[Turn]:
        conn = self._connect()
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM turns WHERE room_id = ?", (room_id,)
            ).fetchone()

            skip = _window_skip(count, self._context_turns, self._context_batch)
            window_size = count - skip

            rows = conn.execute(
                "SELECT role, text FROM turns WHERE room_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (room_id, window_size),
            ).fetchall()
        finally:
            conn.close()

        return [Turn(role=role, text=text) for role, text in reversed(rows)]

    def _append_sync(self, room_id: str, role: str, text: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO turns (room_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                    (room_id, role, text, time.time()),
                )
        finally:
            conn.close()

    def _clear_sync(self, room_id: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute("DELETE FROM turns WHERE room_id = ?", (room_id,))
        finally:
            conn.close()
