"""Tests for memory.py: Summarizer and ConversationMemory. Uses a fake LLM
client (no network, no real model) so these run instantly and deterministically."""

from llm import LLMError, Reply
from memory import RETRY_AFTER_TURNS, ConversationMemory, Summarizer, Turn
from stats import RunStats


class FakeClient:
    """Stands in for OllamaClient. `script` is a list of callables, one per
    expected chat() call, each returning a Reply or raising. Calling past the
    end of the script is a test bug, not something to silently tolerate."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, model, messages, temperature=0.8, max_tokens=None,
              on_token=None, extra_options=None):
        self.calls.append(messages)
        if not self.script:
            raise AssertionError("FakeClient.chat called more times than scripted")
        step = self.script.pop(0)
        return step()


def ok(text, truncated=False):
    return lambda: Reply(text, truncated)


def fail(msg="boom"):
    def _raise():
        raise LLMError(msg)
    return _raise


def turns(n, prefix="turn"):
    return [Turn("Lena" if i % 2 == 0 else "Dev", f"{prefix} {i}") for i in range(n)]


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------

def test_summarizer_condense_returns_cleaned_text():
    client = FakeClient([ok("- Lena mentioned sailing.")])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    result = summ.condense("", [Turn("Lena", "I used to sail.")], "Lena", "Dev")
    assert result == "- Lena mentioned sailing."


def test_summarizer_strips_a_preamble_line():
    client = FakeClient([ok("Here's the updated notes:\n- Lena mentioned sailing.")])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    result = summ.condense("", [Turn("Lena", "hi")], "Lena", "Dev")
    assert result == "- Lena mentioned sailing."


def test_summarizer_drops_a_truncated_trailing_fragment():
    client = FakeClient([ok("- Lena mentioned sailing.\n- Dev asked about the tim", truncated=True)])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    result = summ.condense("", [Turn("Lena", "hi")], "Lena", "Dev")
    assert result == "- Lena mentioned sailing."


def test_summarizer_raises_if_nothing_usable_comes_back():
    client = FakeClient([ok("")])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    try:
        summ.condense("", [Turn("Lena", "hi")], "Lena", "Dev")
        assert False, "expected LLMError"
    except LLMError:
        pass


def test_summarizer_shrinks_an_over_long_summary():
    long_text = " ".join(["word"] * 300)
    short_text = " ".join(["word"] * 100)
    # first call: the condense itself comes back too long; second call: the
    # shrink pass brings it under the limit
    client = FakeClient([ok(long_text), ok(short_text)])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    result = summ.condense("", [Turn("Lena", "hi")], "Lena", "Dev")
    assert len(result.split()) <= 250
    assert len(client.calls) == 2


def test_summarizer_falls_back_to_trimming_if_shrink_fails():
    long_text = " ".join(["word"] * 300)
    client = FakeClient([ok(long_text), fail("shrink broke")])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    result = summ.condense("", [Turn("Lena", "hi")], "Lena", "Dev")
    assert len(result.split()) <= 250


def test_summarizer_falls_back_to_trimming_if_shrink_makes_no_progress():
    long_text = " ".join(["word"] * 300)
    # shrink pass returns something the same length -> no progress -> trim
    client = FakeClient([ok(long_text), ok(long_text)])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    result = summ.condense("", [Turn("Lena", "hi")], "Lena", "Dev")
    assert len(result.split()) <= 250


# ---------------------------------------------------------------------------
# ConversationMemory: recent buffer + condensing
# ---------------------------------------------------------------------------

def make_memory(client, max_recent=6, batch=3, stats=None):
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    return ConversationMemory(summ, max_recent, batch, ["Lena", "Dev"], stats=stats)


def test_add_does_not_condense_before_the_buffer_is_full():
    client = FakeClient([])  # condense should never be called
    mem = make_memory(client, max_recent=6, batch=3)
    for t in turns(5):
        condensed = mem.add(t)
        assert condensed is False
    assert len(mem.recent) == 5


def test_add_condenses_both_summaries_once_the_buffer_fills():
    client = FakeClient([ok("Lena's notes"), ok("Dev's notes")])
    mem = make_memory(client, max_recent=6, batch=3)
    results = [mem.add(t) for t in turns(6)]
    assert results[-1] is True
    assert mem.summary_for("Lena") == "Lena's notes"
    assert mem.summary_for("Dev") == "Dev's notes"
    # the oldest `batch` (3) turns were folded in and removed
    assert len(mem.recent) == 3


def test_condense_calls_are_scoped_to_the_right_owner():
    client = FakeClient([ok("Lena's notes"), ok("Dev's notes")])
    mem = make_memory(client, max_recent=6, batch=3)
    for t in turns(6):
        mem.add(t)
    first_call_system = client.calls[0][0]["content"]
    second_call_system = client.calls[1][0]["content"]
    assert "Lena" in first_call_system and "keep Lena" in first_call_system
    assert "Dev" in second_call_system and "keep Dev" in second_call_system


def test_two_phase_commit_nothing_changes_if_second_person_fails():
    # Lena's condense succeeds, Dev's fails -> neither summary should be
    # committed, so a partial update never becomes visible.
    client = FakeClient([ok("Lena's notes"), fail()])
    mem = make_memory(client, max_recent=6, batch=3)
    for t in turns(6):
        mem.add(t)
    assert mem.summary_for("Lena") == ""
    assert mem.summary_for("Dev") == ""
    assert len(mem.recent) == 6  # nothing was dropped either


def test_a_succeeded_call_is_not_redone_on_retry():
    # Lena succeeds, Dev fails on the first attempt once the buffer fills.
    # RETRY_AFTER_TURNS=2 turns are then skipped entirely (no condense call
    # at all, succeeded or not), and only on the turn after that does a retry
    # fire -- and it should only redo Dev's call, reusing Lena's saved result.
    client = FakeClient([ok("Lena's notes v1"), fail(), ok("Dev's notes v1")])
    mem = make_memory(client, max_recent=6, batch=3)
    for t in turns(6):
        mem.add(t)
    assert len(client.calls) == 2  # Lena succeeded, Dev failed

    mem.add(Turn("Lena", "extra 1"))
    assert len(client.calls) == 2  # skip 1 of 2: no attempt at all
    mem.add(Turn("Dev", "extra 2"))
    assert len(client.calls) == 2  # skip 2 of 2: still no attempt
    condensed = mem.add(Turn("Lena", "extra 3"))
    assert condensed is True
    assert len(client.calls) == 3  # retry fires now: only Dev's call happens

    assert mem.summary_for("Lena") == "Lena's notes v1"
    assert mem.summary_for("Dev") == "Dev's notes v1"


def test_forced_drop_when_summarizer_keeps_failing():
    # Every condense call fails. The buffer is allowed to grow past max_recent
    # while the summarizer is retried, but once it passes 2x max_recent the
    # oldest batch is dropped unsummarized rather than growing without bound.
    stats = RunStats()
    client = FakeClient([fail()] * 50)
    mem = make_memory(client, max_recent=4, batch=2, stats=stats)
    for i in range(20):
        mem.add(Turn("Lena" if i % 2 == 0 else "Dev", f"t{i}"))

    assert stats.memory_forced_drops > 0   # the drop path really ran
    assert stats.memory_condenses == 0     # and nothing was ever summarized
    assert mem.summary_for("Lena") == ""
    assert mem.summary_for("Dev") == ""
    assert len(mem.recent) <= mem.max_recent * 2  # the buffer stayed bounded

    # what survives is the newest turns, still in order, with the oldest gone
    kept = [t.text for t in mem.recent]
    assert "t0" not in kept
    assert kept == [f"t{i}" for i in range(20 - len(kept), 20)]


def test_failed_condense_backs_off_instead_of_retrying_every_turn():
    # A forced drop must not reset the retry countdown: the summarizer is still
    # broken, so it is tried once every RETRY_AFTER_TURNS+1 turns, not once per
    # turn once the buffer is saturated.
    client = FakeClient([fail()] * 50)
    mem = make_memory(client, max_recent=4, batch=2)
    for i in range(20):
        mem.add(Turn("Lena" if i % 2 == 0 else "Dev", f"t{i}"))
    assert len(client.calls) <= 20 // (RETRY_AFTER_TURNS + 1) + 1


def test_stats_are_incremented_on_success_and_failure():
    stats = RunStats()
    client = FakeClient([ok("L"), ok("D")])
    mem = make_memory(client, max_recent=6, batch=3, stats=stats)
    for t in turns(6):
        mem.add(t)
    assert stats.memory_condenses == 1
    assert stats.summarizer_failures == 0

    stats2 = RunStats()
    client2 = FakeClient([ok("L"), fail()])
    mem2 = make_memory(client2, max_recent=6, batch=3, stats=stats2)
    for t in turns(6):
        mem2.add(t)
    assert stats2.summarizer_failures == 1
    assert stats2.memory_condenses == 0


def test_chat_view_roles_are_from_the_speakers_perspective():
    client = FakeClient([])
    mem = make_memory(client, max_recent=6, batch=3)
    # starts with Dev so Lena's view starts on a "user" turn -- no cue needed
    mem.recent = [Turn("Dev", "hi Lena"), Turn("Lena", "hi Dev")]
    view = mem.chat_view("Lena")
    assert view[0] == {"role": "user", "content": "hi Lena"}
    assert view[1] == {"role": "assistant", "content": "hi Dev"}


def test_chat_view_inserts_continuation_cue_when_it_starts_with_own_line():
    client = FakeClient([])
    mem = make_memory(client, max_recent=6, batch=3)
    mem.recent = [Turn("Lena", "hi Dev")]  # only Lena has spoken so far
    view = mem.chat_view("Lena")
    assert view[0]["role"] == "user"  # the inserted cue, not "assistant"
    assert view[1] == {"role": "assistant", "content": "hi Dev"}


def test_condense_batch_must_be_smaller_than_max_recent_turns():
    client = FakeClient([])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    try:
        ConversationMemory(summ, max_recent_turns=4, condense_batch=4, names=["A", "B"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_conversation_memory_requires_exactly_two_names():
    client = FakeClient([])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    try:
        ConversationMemory(summ, max_recent_turns=4, condense_batch=2, names=["A"])
        assert False, "expected ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Per-objective note headings
# ---------------------------------------------------------------------------

def test_each_owner_gets_only_their_own_objective_headings():
    client = FakeClient([ok("Lena's notes"), ok("Dev's notes")])
    summ = Summarizer(client, "m", max_words=250, temperature=0.2)
    mem = ConversationMemory(
        summ, 6, 3, ["Lena", "Dev"],
        note_headings={
            "Lena": "  PROBES LENA USED: ...",
            "Dev": "  WHAT DEV REVEALED: ...",
        },
    )
    for t in turns(6):
        mem.add(t)

    lena_call, dev_call = client.calls[0][0]["content"], client.calls[1][0]["content"]
    assert "PROBES LENA USED" in lena_call
    assert "WHAT DEV REVEALED" not in lena_call
    assert "WHAT DEV REVEALED" in dev_call
    assert "PROBES LENA USED" not in dev_call


def test_the_standard_headings_are_there_with_or_without_objective_headings():
    client = FakeClient([ok("L"), ok("D")])
    mem = make_memory(client, max_recent=6, batch=3)  # no note_headings at all
    for t in turns(6):
        mem.add(t)
    system = client.calls[0][0]["content"]
    assert "WHAT Lena TOLD Dev ABOUT THEMSELVES" in system
    assert "OPEN THREADS" in system
