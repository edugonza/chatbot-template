# Conversation history (`src/history.py`)

Per-room conversation turns, persisted in SQLite at `BOT_HISTORY_DB_PATH`
(default `/data/store/history.db`, inside the persistent volume).

## Storage

```sql
CREATE TABLE turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL,
    role TEXT NOT NULL,      -- "user" | "model"
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX idx_turns_room_id ON turns(room_id, id);
```

- WAL journal mode, 5 s busy timeout.
- A fresh connection per operation, run via `asyncio.to_thread`, so SQLite
  never blocks the event loop.
- **Retention is unbounded**: every turn is kept until `!reset` deletes the
  room's rows.
- History is per room, not per user. In a group room, everyone shares one
  conversation, and the model doesn't see who said what (only the text).

## API

| Method | Does |
|---|---|
| `get(room_id) -> list[Turn]` | The context window, oldest first |
| `append(room_id, role, text)` | Adds one turn |
| `clear(room_id)` | Deletes all turns for the room |

## The context window

What's sent to the model is bounded by `BOT_HISTORY_LENGTH` (`context_turns`,
default 200). The window doesn't slide one turn at a time, though:

```python
def _window_skip(count, context_turns, context_batch):
    excess = count - context_turns
    if excess <= 0:
        return 0
    return (excess // context_batch) * context_batch
```

- Up to `context_turns` turns: send everything.
- Beyond that: drop old turns in multiples of `BOT_HISTORY_BATCH`
  (`context_batch`, default 50).
- So the window holds between `context_turns` and
  `context_turns + context_batch - 1` turns.

**Why:** providers cache prompt prefixes implicitly. A window that slides by
one turn changes the first turn on every call, so the cache never hits. By
jumping in batches, the prefix (system prompt + oldest turns) stays
byte-identical for `context_batch` consecutive calls.

Example with `context_turns=200`, `context_batch=50`:

| Stored turns | Skipped | Sent |
|---|---|---|
| 150 | 0 | 150 |
| 249 | 0 | 249 |
| 250 | 50 | 200 |
| 299 | 50 | 249 |
| 300 | 100 | 200 |

`tests/test_history.py` covers the window arithmetic and persistence.
