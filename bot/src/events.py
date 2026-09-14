"""Helpers for turning raw Matrix event JSON into something handlers can use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import markdown


@dataclass(frozen=True)
class Message:
    room_id: str
    event_id: str
    sender: str
    timestamp_ms: int
    msgtype: str  # "m.text", "m.notice", "m.audio", "m.image", ...
    body: str
    in_reply_to: str | None
    source: dict[str, Any]  # the full event JSON, for anything not lifted out above

    @classmethod
    def from_event(cls, room_id: str, event: dict[str, Any]) -> Message | None:
        """Parse an `m.room.message` event; None for anything we shouldn't act on."""
        if event.get("type") != "m.room.message":
            return None
        content = event.get("content") or {}
        msgtype = content.get("msgtype")
        body = content.get("body")
        if not isinstance(msgtype, str) or not isinstance(body, str):
            return None

        relates_to = content.get("m.relates_to") or {}
        if relates_to.get("rel_type") == "m.replace":
            # Edits arrive as new events; treating them as new messages would
            # make the bot answer twice.
            return None

        return cls(
            room_id=room_id,
            event_id=event.get("event_id", ""),
            sender=event.get("sender", ""),
            timestamp_ms=int(event.get("origin_server_ts", 0)),
            msgtype=msgtype,
            body=body,
            in_reply_to=(relates_to.get("m.in_reply_to") or {}).get("event_id"),
            source=event,
        )


def strip_reply_fallback(body: str) -> str:
    """Strip a Matrix rich-reply's quoted fallback from a message body."""
    lines = body.split("\n")
    while lines and lines[0].startswith("> "):
        lines.pop(0)
    while lines and not lines[0]:
        lines.pop(0)
    return "\n".join(lines)


def markdown_content(
    text: str, *, msgtype: str = "m.text", in_reply_to: str | None = None
) -> dict[str, Any]:
    """Build `m.room.message` content with the Markdown rendered as HTML."""
    content: dict[str, Any] = {
        "msgtype": msgtype,
        "body": text,
        "format": "org.matrix.custom.html",
        "formatted_body": markdown.markdown(text, extensions=["fenced_code"]),
    }
    if in_reply_to:
        content["m.relates_to"] = {"m.in_reply_to": {"event_id": in_reply_to}}
    return content
