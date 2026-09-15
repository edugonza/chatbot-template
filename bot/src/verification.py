"""Policy for interactive (SAS emoji) verification.

The Rust bridge runs the verification protocol; these callbacks only decide
whether to go ahead. Only users in MATRIX_ALLOWED_USERS may verify the bot
(an allowlisted room does not grant it).

The bot has no human to compare emojis with, so it confirms automatically
once the request came from an allowlisted user. The check that matters is
the one *you* do in Element X: the bot posts its emojis in the room (and
logs them) so you can compare them with what your client shows before
tapping "They match".

Verifying a *session* of your own account (rather than another user from a
DM) is a to-device exchange with no room attached. Since that only happens
when the bot's account is one of your own sessions, any room it's allowed
to post in still reaches you, so we fall back to one of those instead of
only logging.
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
        target = room_id or self._fallback_room()
        if target:
            await self._notice(
                target,
                f"🔐 The emojis for verifying {user_id} are:\n\n{line}\n\n"
                "Confirm in your client only if they match exactly.",
            )
        return True

    async def on_verification_done(self, user_id: str, room_id: str | None) -> None:
        logger.info("Verification with %s completed", user_id)
        target = room_id or self._fallback_room()
        if target:
            await self._notice(target, f"✅ Verification with {user_id} complete.")

    async def on_verification_cancelled(
        self, user_id: str, room_id: str | None, reason: str
    ) -> None:
        logger.info("Verification with %s cancelled: %s", user_id, reason)

    def _fallback_room(self) -> str | None:
        """A room to notify in when the verification itself has none.

        To-device verification (typically verifying a second session of the
        bot's own account) carries no room at all. Picking any allowlisted
        room deterministically still reaches the person doing the
        verification, since that only happens when they share the account.
        """
        if not self._settings.allowed_rooms:
            return None
        return min(self._settings.allowed_rooms)

    async def _notice(self, room_id: str, text: str) -> None:
        await self._client.send_message(room_id, markdown_content(text, msgtype="m.notice"))
