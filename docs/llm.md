# LLM, prompts and tools

## `src/llm.py`: `Responder`

The only module that imports `google.genai`. Everything else calls
`await responder.reply(room_id, text) -> str`.

### Construction

- `genai.Client` with HTTP retries (`attempts=5`).
- A single `GenerateContentConfig`, reused on every call:
  - `system_instruction = SYSTEM_PROMPT`
  - `tools = TOOLS`
  - automatic function calling, capped at `max_tool_calls = 10` round trips

### `reply(room_id, message)`

1. Load the room's context window from history (see [history.md](history.md)).
2. Convert each `Turn` to `types.Content(role, parts=[text])` and append the
   new user message.
3. `client.aio.models.generate_content(...)`. The SDK runs any tool calls the
   model makes and feeds the results back until it gets final text.
4. On an exception or empty text: log it and return `FALLBACK_REPLY`. **Nothing
   is saved**, so a failed exchange doesn't pollute history.
5. On success: append the user turn and the model turn, then return the text.

Limitations:

- Tool-call steps aren't stored in history, only final user/model text.
- No streaming: the reply is sent once, when complete.
- Text only: no images or audio are passed to the model.

### Swapping providers

Keep the `reply(room_id, message) -> str` signature and reimplement the class.
`history.py` stores roles as `"user"`/`"model"` (Gemini's naming). Map them if
your provider uses `"assistant"`.

## `src/prompts.py`

`SYSTEM_PROMPT`: short, chat-oriented instructions (keep replies short, use
Markdown only when useful, call tools rather than guess, admit ignorance).
Usually the first thing to change when adapting the template.

## `src/tools.py`

Tools are plain Python functions, sync or async. google-genai builds the
function declaration from:

- the **type hints** (parameter types)
- the **Google-style docstring** (function description + `Args:` descriptions)

Return something JSON-serialisable. List the function in `TOOLS`.

| Tool | Does |
|---|---|
| `get_current_time(timezone)` | ISO timestamp in an IANA timezone; returns an error string for an unknown zone |
| `roll_dice(sides, count)` | Clamps inputs (2–1000 sides, 1–100 dice) and returns the rolls |

Guidelines that follow from the examples:

- **Validate and clamp inputs.** The model chooses the arguments.
- **Return errors as values** (a string the model can read) rather than
  raising, so the model can recover and explain.
- Tools run inside the bot process with its permissions. Anything that
  touches external systems should be scoped accordingly, especially since
  allowlisted rooms can let anyone in the room trigger them.
