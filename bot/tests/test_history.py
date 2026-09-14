import pytest

from src.history import ConversationHistory, Turn


def _history(tmp_path, context_turns=10, context_batch=3):
    return ConversationHistory(
        db_path=str(tmp_path / "history.db"),
        context_turns=context_turns,
        context_batch=context_batch,
    )


@pytest.mark.asyncio
async def test_append_and_get_round_trip(tmp_path):
    history = _history(tmp_path)
    await history.append("!room:matrix.org", "user", "hello")
    await history.append("!room:matrix.org", "model", "hi there")

    assert await history.get("!room:matrix.org") == [
        Turn(role="user", text="hello"),
        Turn(role="model", text="hi there"),
    ]


@pytest.mark.asyncio
async def test_rooms_are_isolated(tmp_path):
    history = _history(tmp_path)
    await history.append("!a:matrix.org", "user", "in room a")
    await history.append("!b:matrix.org", "user", "in room b")

    assert [t.text for t in await history.get("!a:matrix.org")] == ["in room a"]
    assert [t.text for t in await history.get("!b:matrix.org")] == ["in room b"]


@pytest.mark.asyncio
async def test_unknown_room_returns_empty(tmp_path):
    history = _history(tmp_path)
    assert await history.get("!nope:matrix.org") == []


@pytest.mark.asyncio
async def test_context_window_advances_in_batches(tmp_path):
    # cap=3, batch=2: the window's start only jumps forward every 2 new
    # turns, so the returned window oscillates between 3 and 4 turns
    # instead of sliding by one every time.
    history = _history(tmp_path, context_turns=3, context_batch=2)
    for i in range(6):
        await history.append("!room:matrix.org", "user", f"msg{i}")

    assert [t.text for t in await history.get("!room:matrix.org")] == [
        "msg2",
        "msg3",
        "msg4",
        "msg5",
    ]


@pytest.mark.asyncio
async def test_clear_only_affects_one_room(tmp_path):
    history = _history(tmp_path)
    await history.append("!a:matrix.org", "user", "forget me")
    await history.append("!b:matrix.org", "user", "keep me")

    await history.clear("!a:matrix.org")

    assert await history.get("!a:matrix.org") == []
    assert [t.text for t in await history.get("!b:matrix.org")] == ["keep me"]
