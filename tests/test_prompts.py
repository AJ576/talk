"""Tests for prompts.py, plus the wiring that carries a speaker's own objective
and its private reminder into a real request. No network: the Conversation
tests drive a recording fake client."""

import config
from conversation import Conversation
from llm import Reply
from memory import ConversationMemory, Summarizer, Turn
from objectives import Objective
from personas import Persona
from prompts import add_reminder, build_script_message, build_speaker_prompt
from scenarios import Scenario

LENA = Persona(name="Lena", bio="a diver", style="blunt")
DEV = Persona(name="Dev", bio="a baker", style="chatty")

SCENE = Scenario(
    name="testbed",
    setting="You and {partner} are somewhere.",
    opener="(Say hello to {partner}.)",
    first="You got here first.",
    second="You arrived after {partner}.",
)
DIGGING = Objective(
    name="digging", goal="Find out everything about {partner}.",
    reminder="Ask {partner} one more question.",
)
QUIET = Objective(name="quiet", goal="Say as little as possible to {partner}.")
AIMLESS = Objective(name="aimless", goal="Just talk.")


# ---------------------------------------------------------------------------
# add_reminder
# ---------------------------------------------------------------------------

def test_reminder_is_appended_to_the_last_user_message():
    out = add_reminder([{"role": "user", "content": "hello there"}], "ask one more")
    assert out[-1]["content"].startswith("hello there")
    assert "ask one more" in out[-1]["content"]
    assert "never mention it" in out[-1]["content"].lower()


def test_reminder_does_not_mutate_the_history_it_was_given():
    history = [{"role": "user", "content": "hello there"}]
    add_reminder(history, "ask one more")
    assert history == [{"role": "user", "content": "hello there"}]


def test_reminder_only_touches_the_final_message():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "mine"},
        {"role": "user", "content": "second"},
    ]
    out = add_reminder(history, "ask one more")
    assert out[0] == {"role": "user", "content": "first"}
    assert out[1] == {"role": "assistant", "content": "mine"}
    assert "second" in out[2]["content"] and "ask one more" in out[2]["content"]


def test_reminder_is_skipped_when_the_last_message_is_not_from_the_user():
    history = [{"role": "assistant", "content": "mine"}]
    assert add_reminder(history, "ask one more") == history


def test_reminder_is_skipped_on_an_empty_history():
    assert add_reminder([], "ask one more") == []


def test_an_objective_with_no_reminder_changes_nothing():
    history = [{"role": "user", "content": "hello there"}]
    assert add_reminder(history, "") == history


# ---------------------------------------------------------------------------
# build_speaker_prompt
# ---------------------------------------------------------------------------

def test_speaker_prompt_puts_the_objective_last():
    prompt = build_speaker_prompt(LENA, "Dev", "somewhere", "", "Find out everything.")
    assert prompt.rstrip().endswith("Just act on them.")
    assert prompt.index("How you speak") < prompt.index("Find out everything.")


def test_speaker_prompt_without_an_objective_leaves_the_frame_out():
    prompt = build_speaker_prompt(LENA, "Dev", "somewhere", "")
    assert "What you want out of this conversation" not in prompt
    assert "a diver" in prompt and "somewhere" in prompt


def test_speaker_prompt_includes_the_speakers_own_summary():
    prompt = build_speaker_prompt(LENA, "Dev", "somewhere", "Dev mentioned a boat.", "go")
    assert "Dev mentioned a boat." in prompt


def test_speaker_prompt_does_not_hardcode_an_ai_rule():
    # that belongs to the `unmask` objective now, not to every conversation
    prompt = build_speaker_prompt(LENA, "Dev", "somewhere", "", "Just talk.")
    assert "you yourself are an AI" not in prompt


# ---------------------------------------------------------------------------
# build_script_message
# ---------------------------------------------------------------------------

def test_script_message_lists_the_turns_and_asks_for_the_next_one():
    msg = build_script_message([Turn("Lena", "hi"), Turn("Dev", "hey")], "Lena", "Dev")
    assert "Lena: hi" in msg and "Dev: hey" in msg
    assert "Write Lena's next message" in msg


# ---------------------------------------------------------------------------
# What actually reaches the model
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


def build_conversation(client, goals=(DIGGING, QUIET), scenario=SCENE):
    # max_recent is far above the turn count, so no condensing happens and the
    # summarizer client is never called.
    summarizer = Summarizer(client, "m", max_words=250, temperature=0.2)
    memory = ConversationMemory(summarizer, 50, 10, ["Lena", "Dev"])
    return Conversation(
        client, ["m", "m"], [LENA, DEV], list(goals), memory, scenario,
        FakeLog(), FakeLog(),
    )


def system_of(messages):
    return messages[0]["content"]


def last_user(messages):
    return [m for m in messages if m["role"] == "user"][-1]["content"]


def test_each_speaker_gets_their_own_objective(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 2)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["where are you?", "at my desk"])
    build_conversation(client).run()

    lena, dev = system_of(client.requests[0]), system_of(client.requests[1])
    assert "Find out everything about Dev." in lena
    assert "Say as little as possible" not in lena
    assert "Say as little as possible to Lena." in dev
    assert "Find out everything" not in dev


def test_the_reminder_follows_the_speaker_not_the_partner(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 2)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["where are you?", "at my desk"])
    build_conversation(client).run()
    # Lena has a reminder, Dev's objective has none
    assert "Ask Dev one more question." in last_user(client.requests[0])
    assert "Private reminder" not in last_user(client.requests[1])


def test_the_reminder_also_arrives_in_script_mode(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 1)
    monkeypatch.setattr(config, "SCRIPT_MODE", True)
    client = RecordingClient(["where are you?"])
    build_conversation(client).run()
    assert "Ask Dev one more question." in last_user(client.requests[0])


def test_the_reminder_is_never_written_to_the_transcript(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 2)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["where are you?", "at my desk"])
    conversation = build_conversation(client)
    conversation.run()
    assert "Private reminder" not in "".join(conversation.transcript_log.lines)
    # ...and it is not carried into the next request as part of the history
    assert "Private reminder" not in "".join(
        m["content"] for m in client.requests[1][:-1]
    )


def test_each_speaker_gets_their_own_side_of_the_scenario(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 2)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["where are you?", "at my desk"])
    build_conversation(client).run()
    assert "You got here first." in system_of(client.requests[0])
    assert "You arrived after Lena." in system_of(client.requests[1])
    assert "You arrived after" not in system_of(client.requests[0])


def test_the_opener_comes_from_the_scenario(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 1)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["hello there"])
    build_conversation(client).run()
    assert "(Say hello to Dev.)" in last_user(client.requests[0])


def test_the_session_header_records_the_setup(monkeypatch):
    monkeypatch.setattr(config, "MAX_TURNS", 1)
    monkeypatch.setattr(config, "SCRIPT_MODE", False)
    client = RecordingClient(["hello there"])
    conversation = build_conversation(client)
    conversation.run()
    header = conversation.transcript_log.lines[0]
    assert "testbed" in header and "digging vs quiet" in header
