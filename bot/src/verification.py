"""Policy for interactive (SAS emoji) verification.

The Rust bridge runs the verification protocol; these callbacks only decide
whether to go ahead. Only users in MATRIX_ALLOWED_USERS may verify the bot
(an allowlisted room does not grant it).

The bot has no human to compare emojis with, so it confirms automatically
once the request came from an allowlisted user. The check that matters is
the one *you* do in Element X: the bot posts its emojis in the room (and
logs them) so you can compare them with what your client shows before
tapping "They match".
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .config import Settings
from .events import markdown_content

if TYPE_CHECKING:
    from matrix_bridge import Emoji, MatrixClient

logger = logging.getLogger(__name__)


def format_emojis(emojis: Sequence[Emoji]) -> str:
    return "  ".join(f"{emoji.symbol} {emoji.description}" for emoji in emojis)


class VerificationPolicy:
    def __init__(self, client: MatrixClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def on_verification_request(self, user_id: str, room_id: str | None) -> bool:
        if not self._settings.is_user_allowed(user_id):
            logger.warning("Rejecting verification request from disallowed user %s", user_id)
            return False
        logger.info("Accepting verification request from %s (room %s)", user_id, room_id)
        return True

    async def on_verification_emojis(
        self, user_id: str, room_id: str | None, emojis: Sequence[Emoji]
    ) -> bool:
        line = format_emojis(emojis)
        logger.info("Verification emojis with %s: %s", user_id, line)
        if room_id:
            await self._notice(
                room_id,
                f"🔐 The emojis on my side are:\n\n{line}\n\n"
                "Confirm in your client only if they match exactly.",
            )
        return True

    async def on_verification_done(self, user_id: str, room_id: str | None) -> None:
        logger.info("Verification with %s completed", user_id)
        if room_id:
            await self._notice(room_id, "✅ Verification complete.")

    async def on_verification_cancelled(
        self, user_id: str, room_id: str | None, reason: str
    ) -> None:
        logger.info("Verification with %s cancelled: %s", user_id, reason)

    async def _notice(self, room_id: str, text: str) -> None:
        await self._client.send_message(room_id, markdown_content(text, msgtype="m.notice"))
