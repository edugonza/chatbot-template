from src.events import Message, markdown_content, strip_reply_fallback

ROOM = "!room:matrix.org"


def _event(content, **overrides):
    return {
        "type": "m.room.message",
        "event_id": "$event",
        "sender": "@you:matrix.org",
        "origin_server_ts": 1234,
        "content": content,
        **overrides,
    }


def test_text_message_is_parsed():
    message = Message.from_event(ROOM, _event({"msgtype": "m.text", "body": "hi"}))

    assert message is not None
    assert (message.room_id, message.event_id, message.sender) == (ROOM, "$event", "@you:matrix.org")
    assert (message.msgtype, message.body, message.timestamp_ms) == ("m.text", "hi", 1234)
    assert message.in_reply_to is None


def test_reply_target_is_extracted():
    content = {
        "msgtype": "m.text",
        "body": "> quoted\n\nanswer",
        "m.relates_to": {"m.in_reply_to": {"event_id": "$original"}},
    }
    message = Message.from_event(ROOM, _event(content))

    assert message is not None
    assert message.in_reply_to == "$original"


def test_edits_are_ignored():
    content = {
        "msgtype": "m.text",
        "body": "* fixed",
        "m.relates_to": {"rel_type": "m.replace", "event_id": "$original"},
    }
    assert Message.from_event(ROOM, _event(content)) is None


def test_non_message_events_are_ignored():
    assert Message.from_event(ROOM, _event({}, type="m.reaction")) is None
    assert Message.from_event(ROOM, _event({"msgtype": "m.text"})) is None


def test_strip_reply_fallback():
    assert strip_reply_fallback("> <@a:b> quoted\n> more\n\nactual") == "actual"


def test_markdown_content_renders_html_and_reply():
    content = markdown_content("**hi**", in_reply_to="$original")

    assert content["body"] == "**hi**"
    assert content["formatted_body"] == "<p><strong>hi</strong></p>"
    assert content["m.relates_to"] == {"m.in_reply_to": {"event_id": "$original"}}
