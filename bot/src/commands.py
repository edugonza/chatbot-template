"""Chat commands (`!name argument`).

To add one: define a `Command` here, add it to `COMMANDS`, and map it to a
handler method in `BotHandlers.__init__` (src/handlers.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    aliases: tuple[str, ...]
    usage: str
    description: str


HELP = Command(aliases=("!help", "!h"), usage="!help", description="List the available commands.")
PING = Command(aliases=("!ping",), usage="!ping", description="Check that the bot is alive.")
RESET = Command(
    aliases=("!reset",),
    usage="!reset",
    description="Forget the conversation so far in this room.",
)

COMMANDS: tuple[Command, ...] = (HELP, PING, RESET)


def parse_command(body: str, commands: Sequence[Command] = COMMANDS) -> tuple[Command, str] | None:
    """Split `body` into (command, argument) if it starts with a known alias."""
    name, _, argument = body.strip().partition(" ")
    name = name.lower()
    for command in commands:
        if name in command.aliases:
            return command, argument.strip()
    return None


def format_help(commands: Sequence[Command] = COMMANDS) -> str:
    lines = ["**Available commands**", ""]
    for command in commands:
        aliases = " / ".join(f"`{alias}`" for alias in command.aliases)
        lines.append(f"- {aliases} — {command.description}")
    lines.append("")
    lines.append("Anything else is sent to the assistant.")
    return "\n".join(lines)
