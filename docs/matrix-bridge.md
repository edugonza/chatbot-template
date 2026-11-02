# Matrix bridge (`bot/matrix_bridge/`)

A small PyO3 extension that exposes [matrix-rust-sdk](https://github.com/matrix-org/matrix-rust-sdk)
to Python, plus a typed wrapper. It's a uv workspace member built by maturin.

```
matrix_bridge/
├── Cargo.toml                       # matrix-sdk 0.18 (e2e-encryption, automatic-room-key-forwarding, bundled-sqlite)
├── pyproject.toml                   # maturin build backend
├── src/lib.rs                       # the native module `matrix_bridge._native`
└── python/matrix_bridge/
    ├── __init__.py                  # public exports
    └── client.py                    # MatrixClient, handler protocols, dataclasses
```

## Why it exists

- `matrix-nio` (the usual Python SDK) can't do cross-signing or in-room
  verification.
- Element X verifies other users with **in-room verification**: the whole SAS
  handshake is exchanged as events in the DM.
- matrix-rust-sdk (the SDK Element X is built on) supports both, but has no
  official Python bindings.

So the bridge keeps the protocol in Rust and gives Python a narrow async API.

## Native layer (`src/lib.rs`)

### `NativeClient` and `Inner`

- `NativeClient` is the `#[pyclass]` Python holds. It wraps an `Arc<Inner>`.
- `Inner` holds:
  - `client`: the `matrix_sdk::Client`
  - `handler`: the Python object that receives callbacks (the `_Dispatcher`)
  - `locals`: the asyncio loop captured when syncing starts, so Rust can schedule
    coroutines on it
- `Drop` enters the Tokio runtime before dropping `Inner`, because the SDK's
  SQLite pools need a runtime to shut down and Python drops objects on its own
  thread.

### Calling into Python

| Helper | Use |
|---|---|
| `Inner::call(method, args)` | Call `handler.<method>(*args)` on the asyncio loop and await the coroutine |
| `Inner::spawn_call` | Fire-and-forget version, used for events, so Python never blocks the sync loop |
| `Inner::decide` | Yes/no question; any error, missing handler or falsy answer means **no** |

Exceptions raised in Python are printed and logged (`report`), never
propagated into the sync loop.

### Event handlers (`register_event_handlers`)

Registered on the SDK client with a **weak** reference to `Inner`, since the
client owns the handlers and `Inner` owns the client.

| SDK event | Behaviour |
|---|---|
| `StrippedRoomMemberEvent` | If it's an invite for the bot's own user → `on_invite(room_id, sender)` |
| `OriginalSyncRoomMessageEvent` with `msgtype: m.key.verification.request` | In-room verification request → `handle_verification_request` |
| `OriginalSyncRoomMessageEvent` (other) | If the room is joined → `on_message(room_id, raw_json)` (already decrypted) |
| `ToDeviceKeyVerificationRequestEvent` | To-device verification request → `handle_verification_request` |

### Verification state machine

`handle_verification_request`:

1. Ask Python `on_verification_request(user_id, room_id)`. No → `cancel()`.
2. Subscribe to `request.changes()` **before** `accept()`, so the transition
   to SAS can't be missed.
3. On `Transitioned` → if it's SAS, go to `handle_sas`, otherwise cancel
   (QR isn't compiled in).
4. On `Cancelled` → `on_verification_cancelled`.

`handle_sas`:

1. Accept the SAS if the other side started it.
2. On `KeysExchanged` with emojis → spawn a task asking
   `on_verification_emojis(user_id, room_id, [(symbol, description)…])`,
   then `confirm()` or `cancel()`. It's spawned so a cancellation arriving
   while Python decides is still seen.
3. `KeysExchanged` without emojis → cancel (only emoji SAS supported).
4. `Done` → `on_verification_done`; `Cancelled` → `on_verification_cancelled`.

### Methods exposed to Python

| Method | Notes |
|---|---|
| `login(homeserver, user_id, password, store_path, store_passphrase, device_name)` | Password login, creates a new device |
| `restore(homeserver, user_id, device_id, access_token, store_path, store_passphrase)` | Restores a session from an access token |
| `user_id`, `device_id`, `access_token` | Getters |
| `set_handler(obj)` | Sets the callback target |
| `sync_forever()` / `sync_once()` | Captures the running asyncio loop, then syncs (30 s long-poll timeout) |
| `join_room(room_id)` | |
| `send(room_id, event_type, content_json)` | `room.send_raw`; encrypted automatically in encrypted rooms. Returns the event ID |
| `typing(room_id, bool)` | Typing notice |
| `get_event(room_id, event_id)` | Fetches and decrypts one event, returns JSON |
| `download_media(content_json)` | Accepts a `MediaSource` (`url` or encrypted `file`), returns decrypted bytes |
| `cross_signing_status()` | `(has_master, has_self_signing, has_user_signing)` |
| `bootstrap_cross_signing(password=None)` | Tries without auth first (MSC3967), retries with UIAA password auth |
| `reset_cross_signing(password=None, on_approval_url=None)` | Handles both UIAA (password) and OAuth/MAS (browser approval URL) |

Errors surface in Python as `matrix_bridge.MatrixError`.

### Logging (`init_logging`)

- `MATRIX_SDK_LOG_LEVEL` sets the level for the whole Rust side (default `warn`).
- Without it, `matrix_sdk::http_client` is silenced (it logs expected 404s as
  errors) and `matrix_sdk_crypto::backups` is capped at `error` (key backup
  isn't set up, so it would warn on every message).

## Python wrapper (`python/matrix_bridge/client.py`)

Bot code imports only this. It adapts types and never exposes `_native`.

- **`MatrixClient`**: `login` / `restore` classmethods, plus `send_message`,
  `set_typing`, `join_room`, `get_event`, `download_media`,
  `cross_signing_status`, `bootstrap_cross_signing`, `reset_cross_signing`,
  `sync_forever`, `sync_once`, `session()`.
- **`EventHandler`** protocol: `on_invite`, `on_message(room_id, event: dict)`.
- **`VerificationHandler`** protocol: `on_verification_request`,
  `on_verification_emojis`, `on_verification_done`, `on_verification_cancelled`.
  `room_id` is `None` for to-device verification.
- **`_Dispatcher`**: the object actually handed to Rust. It decodes JSON and
  tuples into Python types, and wraps every call in `_guard`, which logs
  exceptions and returns a safe default (`False` for decisions).
- **Dataclasses**: `Session`, `CrossSigningStatus` (with `is_complete`), `Emoji`.

`set_handlers(events=..., verification=...)` must be called before syncing.
Without a verification handler, every verification request is cancelled.

## Building

- Local: `uv sync` in `bot/` compiles it (Rust ≥ 1.93). After editing
  `lib.rs`: `uv sync --reinstall-package matrix-bridge`.
- Docker: the build stage compiles it into a wheel (`--no-editable`), so the
  runtime image carries no toolchain.
- Release profile: thin LTO, stripped.

## Adding a capability

1. Add a `#[pymethods]` method on `NativeClient` that returns
   `future_into_py(...)`. Pass complex data as JSON strings.
2. Add a typed wrapper method on `MatrixClient`.
3. For new *incoming* event types, add a handler in `register_event_handlers`
   that uses `spawn_call`, and a matching method on `_Dispatcher` and the
   protocol.
