from pheme.commands import ReplyLast, SendSms, Usage, parse_command

BOT = "@phemebot:example.org"
USER = "@alice:example.org"


def test_valid_sms():
    cmd = parse_command("!sms +33612345678 Hello from the CPE", USER, BOT)
    assert isinstance(cmd, SendSms)
    assert cmd.number == "+33612345678"
    assert cmd.text == "Hello from the CPE"


def test_sms_number_without_plus():
    cmd = parse_command("!sms 0612345678 hi", USER, BOT)
    assert isinstance(cmd, SendSms)
    assert cmd.number == "0612345678"


def test_reply():
    cmd = parse_command("!reply on my way", USER, BOT)
    assert isinstance(cmd, ReplyLast)
    assert cmd.text == "on my way"


def test_sms_missing_text_is_usage():
    assert isinstance(parse_command("!sms +33612345678", USER, BOT), Usage)


def test_reply_missing_text_is_usage():
    assert isinstance(parse_command("!reply", USER, BOT), Usage)


def test_invalid_number_is_usage():
    assert isinstance(parse_command("!sms notanumber hello", USER, BOT), Usage)


def test_unknown_command_is_usage():
    assert isinstance(parse_command("!foo bar", USER, BOT), Usage)


def test_plain_message_is_ignored():
    assert parse_command("just chatting in the room", USER, BOT) is None


def test_own_message_is_ignored():
    # Filtering on sender prevents the bot from acting on its own confirmations.
    assert parse_command("!sms +33612345678 loop", BOT, BOT) is None


def test_empty_message_is_ignored():
    assert parse_command("", USER, BOT) is None


def test_leading_whitespace_is_stripped():
    cmd = parse_command("   !reply  spaced  ", USER, BOT)
    assert isinstance(cmd, ReplyLast)
    assert cmd.text == "spaced"
