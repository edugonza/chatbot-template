"""Gemini-backed responder: system prompt + per-room history + tool calling."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from google import genai
from google.genai import types

from .history import ConversationHistory, Turn
from .prompts import SYSTEM_PROMPT
from .tools import TOOLS

logger = logging.getLogger(__name__)

FALLBACK_REPLY = "Sorry, I ran into a problem talking to the language model just now. Please try again."


class Responder:
    def __init__(
        self,
        api_key: str,
        model: str,
        history: ConversationHistory,
        tools: Sequence[Callable[..., Any]] = TOOLS,
        max_tool_calls: int = 10,
    ) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=5)),
        )
        self._model = model
        self._history = history
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=list(tools),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=max_tool_calls
            ),
        )

    async def reply(self, room_id: str, message: str) -> str:
        history = await self._history.get(room_id)
        contents = [_to_content(turn) for turn in history]
        contents.append(_to_content(Turn(role="user", text=message)))

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=self._config,
            )
            text = (response.text or "").strip()
        except Exception:
            logger.exception("Model request failed for room %s", room_id)
            return FALLBACK_REPLY

        if not text:
            logger.warning("Model returned an empty reply for room %s", room_id)
            return FALLBACK_REPLY

        await self._history.append(room_id, "user", message)
        await self._history.append(room_id, "model", text)
        return text


def _to_content(turn: Turn) -> types.Content:
    return types.Content(role=turn.role, parts=[types.Part(text=turn.text)])
