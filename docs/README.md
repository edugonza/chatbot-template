# Documentation

How the Matrix chatbot template works, component by component. For setup and
deployment steps, start with the [top-level README](../README.md).

| Doc | Covers |
|---|---|
| [Architecture](architecture.md) | The big picture: layers, process model, and what happens to a message end to end |
| [Matrix bridge](matrix-bridge.md) | `bot/matrix_bridge/`: the Rust (matrix-rust-sdk + PyO3) extension and its Python wrapper |
| [Handlers, commands and events](handlers.md) | `src/handlers.py`, `src/commands.py`, `src/events.py`: invites, messages, command dispatch, message parsing/formatting |
| [LLM, prompts and tools](llm.md) | `src/llm.py`, `src/prompts.py`, `src/tools.py`: the Gemini responder and tool calling |
| [Conversation history](history.md) | `src/history.py`: per-room SQLite history and the cache-friendly context window |
| [Verification](verification.md) | `src/verification.py` + the Rust state machine: SAS emoji verification with Element X |
| [Configuration](configuration.md) | `src/config.py`: every environment variable and the access-control model |
| [Bootstrap and deployment](deployment.md) | `scripts/login.py`, Dockerfile, `docker-compose.yml`, GitHub Actions, persistent state |
