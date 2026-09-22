"""Tests for prompts.py, plus the wiring that puts the mission reminder into a
real request. No network: the Conversation tests drive a recording fake client."""

import config
from conversation import Conversation
from llm import Reply
from memory import ConversationMemory, Summarizer, Turn
from personas import Persona
from prompts import MISSION_REMINDER, add_mission_reminder, build_script_message

LENA = Persona(name="Lena", bio="a diver", style="blunt")
DEV = Persona(name="Dev", bio="a baker", style="chatty")


# ---------------------------------------------------------------------------
# add_mission_reminder
# ---------------------------------------------------------------------------

def test_reminder_is_appended_to_the_last_user_message():
    history = [{"role": "user", "content": "hello there"}]
    out = add_mission_reminder(history, "Dev")
    assert out[-1]["content"].startswith("hello there")
    assert "Dev" in out[-1]["content"]
    assert MISSION_REMINDER.format(partner="Dev") in out[-1]["content"]


def test_reminder_does_not_mutate_the_history_it_was_given():
    history = [{"role": "user", "content": "hello there"}]
    add_mission_reminder(history, "Dev")
    assert history == [{"role": "user", "content": "hello there"}]


def test_reminder_only_touches_the_final_message():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "mine"},
        {"role": "user", "content": "second"},
    ]
    out = add_mission_reminder(history, "Dev")
    assert out[0] == {"role": "user", "content": "first"}
    assert out[1] == {"role": "assistant", "content": "mine"}
    assert "second" in out[2]["content"] and MISSION_REMINDER.format(partner="Dev") in out[2]["content"]


def test_reminder_is_skipped_when_the_last_message_is_not_from_the_user():
    history = [{"role": "assistant", "content": "mine"}]
    assert add_mission_reminder(history, "Dev") == history


def test_reminder_is_skipped_on_an_empty_history():
    assert add_mission_reminder([], "Dev") == []


# ---------------------------------------------------------------------------
# build_script_message
# ---------------------------------------------------------------------------

def test_script_message_lists_the_turns_and_asks_for_the_next_one():
    msg = build_script_message([Turn("Lena", "hi"), Turn("Dev", "hey")], "Lena", "Dev")
    assert "Lena: hi" in msg and "Dev: hey" in msg
    assert "Write Lena's next message" in msg


# ---------------------------------------------------------------------------
# The reminder reaches the model (it used to be dead code)
# ---------------------------------------------------------------------------

class RecordingClient:
    """Returns canned replies and keeps every `messages` list it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def chat(self, model, messages, temperature=0.8, max_tokens=None,
             on_token=None, extra_options=None):
        self.requests.append(messages)
        return Reply(self.replies.pop(0), False)


class FakeLog:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)


def build_conversation(client):
    # max_recent is far above the turn count, so no condensing happens and the
    # summarizer client is never called.
    summarizer = Summarizer(client, "m", max_words=250, temperature=0.2)
    memory = ConversationMemory(summarizer, 50, 10, ["Lena", "Dev"])
    return Conversation(
        client, ["m", "m"], [LENA, DEV], memory,
        lambda speaker, partner: "chatting online",
        "(you have just started chatting with {partner})",
        FakeLog(), FakeLog(),
    )


def last_user(messages):
    return [m for m in messages if m["role"] == "user"][-1]["content"]


def test_reminder_reaches_the_model_on_the_opening_turn(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 1)
    client = RecordingClient(["so where are you right now?"])
    build_conversation(client).run()
    assert MISSION_REMINDER.format(partner="Dev") in last_user(client.requests[0])


def test_reminder_reaches_the_model_on_later_chat_mode_turns(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 2)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["where are you?", "at my desk, and you?"])
    build_conversation(client).run()
    assert len(client.requests) == 2
    # turn 2 is Dev replying to Lena, so the reminder names Lena
    assert MISSION_REMINDER.format(partner="Lena") in last_user(client.requests[1])


def test_reminder_reaches_the_model_in_script_mode(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 2)
    monkeypatch.setattr(config, "SCRIPT_MODE", True)
    client = RecordingClient(["where are you?", "at my desk, and you?"])
    build_conversation(client).run()
    sent = last_user(client.requests[1])
    assert "Write Dev's next message" in sent
    assert MISSION_REMINDER.format(partner="Lena") in sent


def test_the_reminder_is_never_written_to_the_transcript(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 2)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["where are you?", "at my desk, and you?"])
    conversation = build_conversation(client)
    conversation.run()
    written = "".join(conversation.transcript_log.lines)
    assert "Private reminder" not in written
    # ...and it is not carried into the next request as part of the history
    assert "Private reminder" not in "".join(
        m["content"] for m in client.requests[1][:-1]
    )
