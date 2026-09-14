"""Tools the model may call while answering.

A tool is a plain function (sync or async) with type hints and a Google-style
docstring: google-genai turns the signature and docstring into the function
declaration the model sees, and runs the call for you. To add a tool, write
the function and list it in `TOOLS`. Return something JSON-serialisable.
"""

from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


async def get_current_time(timezone: str) -> str:
    """Get the current date and time.

    Args:
        timezone: IANA timezone name, for example "Europe/Amsterdam" or "UTC".
    """
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return f"Unknown timezone: {timezone}"
    return datetime.now(tz).isoformat(timespec="seconds")


def roll_dice(sides: int, count: int) -> list[int]:
    """Roll one or more dice.

    Args:
        sides: Number of sides on each die (2-1000).
        count: How many dice to roll (1-100).
    """
    sides = max(2, min(sides, 1000))
    count = max(1, min(count, 100))
    return [random.randint(1, sides) for _ in range(count)]


TOOLS = (get_current_time, roll_dice)
