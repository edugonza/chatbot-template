"""Pythonic wrapper around the native matrix-rust-sdk bindings.

Everything protocol-heavy — syncing, end-to-end encryption, cross-signing and
the SAS (emoji) verification state machine — runs in Rust on a Tokio runtime.
This module only adapts types (JSON <-> dict, tuples <-> dataclasses) so bot
code can stay plain asyncio Python and never touch the native module directly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from ._native import NativeClient

logger = logging.getLogger("matrix_bridge")

T = TypeVar("T")


@dataclass(frozen=True)
class Session:
    user_id: str
    device_id: str
    access_token: str


@dataclass(frozen=True)
class CrossSigningStatus:
    has_master: bool
    has_self_signing: bool
    has_user_signing: bool

    @property
    def is_complete(self) -> bool:
        """True when this device holds all three private cross-signing keys."""
        return self.has_master and self.has_self_signing and self.has_user_signing


@dataclass(frozen=True)
class Emoji:
    symbol: str
    description: str


class EventHandler(Protocol):
    async def on_invite(self, room_id: str, sender: str) -> None: ...

    async def on_message(self, room_id: str, event: dict[str, Any]) -> None:
        """Called for every (decrypted) `m.room.message` in a joined room.

        `event` is the raw event JSON as a dict — the same shape as the
        Matrix spec, minus `room_id`, which is passed separately.
        """
        ...


class VerificationHandler(Protocol):
    """Decisions for an interactive verification; the protocol itself runs in Rust.

    `room_id` is set for in-room verification (what Element X uses when you
    verify another user from a DM) and `None` for to-device verification.
    """

    async def on_verification_request(self, user_id: str, room_id: str | None) -> bool:
        """Return True to accept the request, False to cancel it."""
        ...

    async def on_verification_emojis(
        self, user_id: str, room_id: str | None, emojis: Sequence[Emoji]
    ) -> bool:
        """Return True to confirm the emojis match, False to cancel."""
        ...

    async def on_verification_done(self, user_id: str, room_id: str | None) -> None: ...

    async def on_verification_cancelled(
        self, user_id: str, room_id: str | None, reason: str
    ) -> None: ...


class _Dispatcher:
    """The object the native layer calls into.

    It decodes arguments into Python types and makes sure an exception in a
    handler gets logged here, instead of surfacing on a Tokio worker thread.
    """

    def __init__(
        self, events: EventHandler | None, verification: VerificationHandler | None
    ) -> None:
        self._events = events
        self._verification = verification

    async def on_invite(self, room_id: str, sender: str) -> None:
        if self._events is not None:
            await _guard("on_invite", self._events.on_invite(room_id, sender), None)

    async def on_message(self, room_id: str, event_json: str) -> None:
        if self._events is not None:
            event = json.loads(event_json)
            await _guard("on_message", self._events.on_message(room_id, event), None)

    async def on_verification_request(self, user_id: str, room_id: str | None) -> bool:
        if self._verification is None:
            return False
        coro = self._verification.on_verification_request(user_id, room_id)
        return bool(await _guard("on_verification_request", coro, False))

    async def on_verification_emojis(
        self, user_id: str, room_id: str | None, emojis: list[tuple[str, str]]
    ) -> bool:
        if self._verification is None:
            return False
        parsed = [Emoji(symbol, description) for symbol, description in emojis]
        coro = self._verification.on_verification_emojis(user_id, room_id, parsed)
        return bool(await _guard("on_verification_emojis", coro, False))

    async def on_verification_done(self, user_id: str, room_id: str | None) -> None:
        if self._verification is not None:
            coro = self._verification.on_verification_done(user_id, room_id)
            await _guard("on_verification_done", coro, None)

    async def on_verification_cancelled(
        self, user_id: str, room_id: str | None, reason: str
    ) -> None:
        if self._verification is not None:
            coro = self._verification.on_verification_cancelled(user_id, room_id, reason)
            await _guard("on_verification_cancelled", coro, None)


async def _guard(name: str, coro: Awaitable[T], default: T) -> T:
    try:
        return await coro
    except Exception:
        logger.exception("Unhandled error in %s handler", name)
        return default


class MatrixClient:
    """A logged-in Matrix client backed by matrix-rust-sdk.

    Create one with `login` (once, to create a device) or `restore` (every
    run afterwards). Both need the same `store_path`: it holds the SQLite
    state and crypto stores, which must survive restarts.
    """

    def __init__(self, native: NativeClient) -> None:
        self._native = native

    @classmethod
    async def login(
        cls,
        *,
        homeserver: str,
        user_id: str,
        password: str,
        store_path: str,
        store_passphrase: str | None = None,
        device_name: str = "chatbot",
    ) -> MatrixClient:
        native = await NativeClient.login(
            homeserver, user_id, password, store_path, store_passphrase, device_name
        )
        return cls(native)

    @classmethod
    async def restore(
        cls,
        *,
        homeserver: str,
        user_id: str,
        device_id: str,
        access_token: str,
        store_path: str,
        store_passphrase: str | None = None,
    ) -> MatrixClient:
        native = await NativeClient.restore(
            homeserver, user_id, device_id, access_token, store_path, store_passphrase
        )
        return cls(native)

    @property
    def user_id(self) -> str:
        return self._native.user_id

    @property
    def device_id(self) -> str:
        return self._native.device_id

    def session(self) -> Session:
        return Session(self._native.user_id, self._native.device_id, self._native.access_token)

    def set_handlers(
        self,
        *,
        events: EventHandler | None = None,
        verification: VerificationHandler | None = None,
    ) -> None:
        """Register the callbacks; call before syncing. Replaces earlier handlers.

        Without a verification handler every verification request is cancelled.
        """
        self._native.set_handler(_Dispatcher(events, verification))

    async def sync_forever(self) -> None:
        """Sync until cancelled (cancel the awaiting task to stop)."""
        await self._native.sync_forever()

    async def sync_once(self) -> None:
        await self._native.sync_once()

    async def join_room(self, room_id: str) -> None:
        await self._native.join_room(room_id)

    async def send_message(
        self, room_id: str, content: dict[str, Any], *, event_type: str = "m.room.message"
    ) -> str:
        """Send a message-like event (encrypted if the room is); returns its event ID."""
        return await self._native.send(room_id, event_type, json.dumps(content))

    async def set_typing(self, room_id: str, typing: bool) -> None:
        await self._native.typing(room_id, typing)

    async def get_event(self, room_id: str, event_id: str) -> dict[str, Any]:
        """Fetch (and decrypt, if needed) a single event from a room."""
        return json.loads(await self._native.get_event(room_id, event_id))

    async def download_media(self, content: dict[str, Any]) -> bytes:
        """Download the media referenced by a message's `content` (`url` or encrypted `file`)."""
        return await self._native.download_media(json.dumps(content))

    async def cross_signing_status(self) -> CrossSigningStatus:
        return CrossSigningStatus(*await self._native.cross_signing_status())

    async def bootstrap_cross_signing(self, password: str | None = None) -> CrossSigningStatus:
        """Create a cross-signing identity if the account has none yet.

        A no-op when the account already has one — check `is_complete` on the
        result to see whether *this* device holds the private keys.
        """
        return CrossSigningStatus(*await self._native.bootstrap_cross_signing(password))

    async def reset_cross_signing(
        self,
        password: str | None = None,
        on_approval_url: Callable[[str], None] | None = None,
    ) -> CrossSigningStatus:
        """Replace the account's cross-signing identity with a fresh one owned by this device.

        Servers using OAuth (MAS) need the reset approved in a browser:
        `on_approval_url` receives that URL, and this call waits until approved.
        """
        status = await self._native.reset_cross_signing(password, on_approval_url)
        return CrossSigningStatus(*status)
