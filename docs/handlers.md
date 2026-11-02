# Handlers, commands and events

## `src/handlers.py`: `BotHandlers`

Implements the bridge's `EventHandler` protocol. Built in `main.py` with the
client, settings, responder and history.

### `on_invite(room_id, sender)`

- Ignores the invite unless `sender` is in `MATRIX_ALLOWED_USERS` or `room_id`
  is in `MATRIX_ALLOWED_ROOMS`.
- Joins with up to `JOIN_ATTEMPTS = 5` tries and exponential backoff
  (2, 4, 8, 16 s). Synapse can deliver an invite before a join is accepted.

### `on_message(room_id, event)`

A chain of filters, then one reply:

1. `Message.from_event` returns `None` → ignore (not a message, no body, or an edit).
2. Sent by the bot itself → ignore.
3. `origin_server_ts` older than the bot's start time → ignore. The bot doesn't
   answer backlog after a restart.
4. Sender/room not allowlisted → ignore (logged).
5. `msgtype != "m.text"` → ignore. This is the extension point for images and
   voice: `client.download_media(message.source["content"])` returns decrypted bytes.
6. Under the room's `asyncio.Lock`:
   - set typing on
   - strip the rich-reply fallback (`> …` quoted lines)
   - if it parses as a command, run the command handler, otherwise
     `responder.reply(room_id, body)`
   - send the reply as Markdown-rendered HTML (sending clears the typing indicator)

The per-room lock exists because the bridge runs callbacks concurrently.
Without it, two quick messages could be answered out of order.

### Command handlers

`self._commands` maps each `Command` to an async method
`(message, argument) -> str`. The returned string is sent as Markdown.

| Command | Handler | Does |
|---|---|---|
| `!help`, `!h` | `_handle_help` | `format_help()` |
| `!ping` | `_handle_ping` | `pong 🏓` |
| `!reset` | `_handle_reset` | Clears the room's history |

## `src/commands.py`

- `Command(aliases, usage, description)`: a frozen dataclass.
- `COMMANDS`: the ordered tuple used for parsing and help.
- `parse_command(body)`: splits on the first space, lowercases the name, and
  returns `(command, argument)` if the name matches an alias.
- `format_help()`: a Markdown list of aliases and descriptions.

To add a command:

1. Define the `Command` and add it to `COMMANDS`.
2. Write `_handle_<name>` in `BotHandlers` and map it in `__init__`.

If a command is in `COMMANDS` but not mapped, `on_message` will raise a
`KeyError`. `tests/test_commands.py` covers the parsing.

## `src/events.py`

### `Message`

A frozen dataclass lifted out of raw `m.room.message` JSON:

| Field | From |
|---|---|
| `room_id` | passed separately by the bridge |
| `event_id`, `sender` | top level |
| `timestamp_ms` | `origin_server_ts` |
| `msgtype`, `body` | `content` |
| `in_reply_to` | `content["m.relates_to"]["m.in_reply_to"]["event_id"]` |
| `source` | the full event, for anything not lifted out |

`from_event` returns `None` for:

- non-`m.room.message` events
- content without a string `msgtype` or `body`
- **edits** (`rel_type: m.replace`): they arrive as new events, and answering
  them would make the bot reply twice

### `strip_reply_fallback(body)`

Removes leading `> ` quote lines and the blank line after them, which older
clients prepend to replies.

### `markdown_content(text, msgtype="m.text", in_reply_to=None)`

Builds message content with both `body` (plain Markdown) and `formatted_body`
(HTML via `markdown` + `fenced_code`, `format: org.matrix.custom.html`).
Optionally adds an `m.in_reply_to` relation. Use `msgtype="m.notice"` for
bot notices (clients render them differently, and bots conventionally don't
respond to notices).
