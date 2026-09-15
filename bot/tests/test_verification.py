from collections import namedtuple

import pytest

from src.config import Settings
from src.verification import VerificationPolicy, format_emojis

Emoji = namedtuple("Emoji", "symbol description")


class FakeClient:
    def __init__(self):
        self.sent = []

    async def send_message(self, room_id, content, *, event_type="m.room.message"):
        self.sent.append((room_id, content))
        return "$sent"


def _settings(allowed_rooms=frozenset({"!room:matrix.org"})):
    return Settings(
        matrix_homeserver="https://matrix.org",
        matrix_user_id="@bot:matrix.org",
        matrix_access_token="token",
        matrix_device_id="DEVICE",
        matrix_store_path="/tmp/store",
        matrix_store_passphrase=None,
        allowed_users=frozenset({"@you:matrix.org"}),
        allowed_rooms=allowed_rooms,
        gemini_api_key="key",
        gemini_model="model",
    )


@pytest.mark.asyncio
async def test_only_allowlisted_users_may_verify():
    policy = VerificationPolicy(FakeClient(), _settings())

    assert await policy.on_verification_request("@you:matrix.org", "!room:matrix.org")
    assert not await policy.on_verification_request("@stranger:matrix.org", "!room:matrix.org")


@pytest.mark.asyncio
async def test_emojis_are_posted_to_the_room_and_confirmed():
    client = FakeClient()
    policy = VerificationPolicy(client, _settings())
    emojis = [Emoji("🐶", "Dog"), Emoji("🔑", "Key")]

    assert await policy.on_verification_emojis("@you:matrix.org", "!room:matrix.org", emojis)

    [(room_id, content)] = client.sent
    assert room_id == "!room:matrix.org"
    assert content["msgtype"] == "m.notice"
    assert "🐶 Dog  🔑 Key" in content["body"]


@pytest.mark.asyncio
async def test_to_device_verification_falls_back_to_an_allowed_room():
    client = FakeClient()
    policy = VerificationPolicy(client, _settings())

    assert await policy.on_verification_emojis("@you:matrix.org", None, [Emoji("🐶", "Dog")])

    [(room_id, content)] = client.sent
    assert room_id == "!room:matrix.org"
    assert content["msgtype"] == "m.notice"
    assert "🐶 Dog" in content["body"]


@pytest.mark.asyncio
async def test_to_device_verification_sends_nothing_without_an_allowed_room():
    client = FakeClient()
    policy = VerificationPolicy(client, _settings(allowed_rooms=frozenset()))

    assert await policy.on_verification_emojis("@you:matrix.org", None, [Emoji("🐶", "Dog")])
    assert client.sent == []


def test_format_emojis():
    assert format_emojis([Emoji("🐶", "Dog"), Emoji("🔑", "Key")]) == "🐶 Dog  🔑 Key"
