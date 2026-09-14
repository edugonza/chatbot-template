from src.commands import COMMANDS, HELP, RESET, format_help, parse_command


def test_known_command_with_argument():
    assert parse_command("!reset now please") == (RESET, "now please")


def test_alias_is_case_insensitive():
    assert parse_command("!H") == (HELP, "")


def test_plain_text_is_not_a_command():
    assert parse_command("what is !help?") is None


def test_unknown_command_is_not_a_command():
    assert parse_command("!nope") is None


def test_help_lists_every_alias():
    text = format_help()
    for command in COMMANDS:
        for alias in command.aliases:
            assert f"`{alias}`" in text
