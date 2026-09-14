"""Matrix event callbacks: invites, chat messages and commands."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .commands import HELP, PING, RESET, format_help, parse_command
from .config import Settings
from .events import Message, markdown_content, strip_reply_fallback
from .history import ConversationHistory
from .llm import Responder

if TYPE_CHECKING:
    from matrix_bridge import MatrixClient

logger = logging.getLogger(__name__)

JOIN_ATTEMPTS = 5


class BotHandlers:
    def __init__(
        self,
        client: MatrixClient,
        settings: Settings,
        responder: Responder,
        history: ConversationHistory,
    ) -> None:
        self._client = client
        self._settings = settings
        self._responder = responder
        self._history = history
        self._start_ms = time.time() * 1000
        # Callbacks run concurrently; the lock keeps replies within a room in
        # the order the messages arrived.
        self._room_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._commands = {
            HELP: self._handle_help,
            PING: self._handle_ping,
            RESET: self._handle_reset,
        }

    def _is_allowed(self, sender: str, room_id: str) -> bool:
        return self._settings.is_user_allowed(sender) or self._settings.is_room_allowed(room_id)

    async def on_invite(self, room_id: str, sender: str) -> None:
        if not self._is_allowed(sender, room_id):
            logger.info("Ignoring invite to %s from disallowed user %s", room_id, sender)
            return

        logger.info("Joining room %s (invited by %s)", room_id, sender)
        for attempt in range(1, JOIN_ATTEMPTS + 1):
            try:
                await self._client.join_room(room_id)
                return
            except Exception:
                # Synapse can deliver the invite before the join is accepted.
                if attempt == JOIN_ATTEMPTS:
                    logger.exception("Giving up joining room %s", room_id)
                    return
                delay = 2**attempt
                logger.warning("Failed to join %s, retrying in %ds", room_id, delay)
                await asyncio.sleep(delay)

    async def on_message(self, room_id: str, event: dict[str, Any]) -> None:
        message = Message.from_event(room_id, event)
        if message is None or message.sender == self._client.user_id:
            return
        if message.timestamp_ms < self._start_ms:
            return
        if not self._is_allowed(message.sender, room_id):
            logger.info("Ignoring message in %s from disallowed user %s", room_id, message.sender)
            return
        if message.msgtype != "m.text":
            # Extend here for voice notes, images, ... — `client.download_media(
            # message.source["content"])` returns the (decrypted) bytes.
            return

        async with self._room_locks[room_id]:
            await self._client.set_typing(room_id, True)

            body = strip_reply_fallback(message.body.strip())
            parsed = parse_command(body)
            if parsed is not None:
                command, argument = parsed
                reply = await self._commands[command](message, argument)
            else:
                reply = await self._responder.reply(room_id, body)

            # Sending the reply clears the typing indicator in clients.
            await self._client.send_message(room_id, markdown_content(reply))

    async def _handle_help(self, message: Message, argument: str) -> str:
        return format_help()

    async def _handle_ping(self, message: Message, argument: str) -> str:
        return "pong 🏓"

    async def _handle_reset(self, message: Message, argument: str) -> str:
        await self._history.clear(message.room_id)
        return "Okay, I've forgotten our conversation in this room."
