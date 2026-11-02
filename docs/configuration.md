# Configuration (`src/config.py`)

All configuration comes from environment variables. `Settings.from_env()`
builds a frozen `Settings` dataclass at startup and raises `ConfigError` for
missing required values.

## Variables

### Matrix

| Variable | Required | Default | Notes |
|---|---|---|---|
| `MATRIX_HOMESERVER` | no | `https://matrix.org` | A server name or homeserver URL |
| `MATRIX_USER_ID` | yes | | e.g. `@mybot:matrix.org` |
| `MATRIX_ACCESS_TOKEN` | yes | | From `scripts/login.py` |
| `MATRIX_DEVICE_ID` | yes | | From `scripts/login.py`; must match the crypto store |
| `MATRIX_STORE_PATH` | no | `/data/store` | SQLite state + crypto stores |
| `MATRIX_STORE_PASSPHRASE` | no | | Encrypts the stores at rest. Must be identical at login and forever after |

### Access control

| Variable | Notes |
|---|---|
| `MATRIX_ALLOWED_USERS` | Comma-separated MXIDs |
| `MATRIX_ALLOWED_ROOMS` | Comma-separated room IDs (`!abc:server`) |

At least one of them must be set. Values are trimmed, and empty items are ignored.

### Model

| Variable | Required | Default |
|---|---|---|
| `GEMINI_API_KEY` | yes | |
| `GEMINI_MODEL` | no | `gemini-3.5-flash-lite` |

### History

| Variable | Default | Notes |
|---|---|---|
| `BOT_HISTORY_DB_PATH` | `/data/store/history.db` | |
| `BOT_HISTORY_LENGTH` | `200` | Minimum turns in the context window |
| `BOT_HISTORY_BATCH` | `50` | Window advance step (see [history.md](history.md)) |

### Logging and one-off

| Variable | Read by | Default |
|---|---|---|
| `LOG_LEVEL` | `main.py` (Python logging) | `INFO` |
| `MATRIX_SDK_LOG_LEVEL` | the Rust bridge | `warn`, with noisy targets muted |
| `MATRIX_PASSWORD` | `scripts/login.py` only; never set it on the running bot | prompted |
| `MATRIX_DEVICE_NAME` | `scripts/login.py` | `chatbot` |

## Access-control model

| Action | Allowed if |
|---|---|
| Bot joins on invite | inviter ∈ users **or** room ∈ rooms |
| Bot answers a message | sender ∈ users **or** room ∈ rooms |
| Bot accepts verification | user ∈ users (rooms don't count) |

The two lists are **additive**. An allowlisted room lets *anyone* in it talk
to the bot, including tool calls, so keep room membership in mind.

`tests/test_config.py` covers parsing and validation.
