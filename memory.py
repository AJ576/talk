"""Conversation memory: recent turns verbatim + one rolling summary per person.

Both people heard the same recent turns, so there is a single verbatim buffer.
What differs is the summary: each person has their own notes, written from their
side, so each remembers the older conversation a little differently.

The Summarizer is a separate model that never sees the live conversation. It is
only ever handed "one person's old notes + a chunk of old transcript" and returns
that person's new notes.
"""

import re
from dataclasses import dataclass

from llm import LLMError
from prompts import build_shrink_messages, build_summarizer_messages

# Used when the verbatim window happens to begin with the speaker's own line,
# because most chat models expect the first message to come from the "user".
CONTINUATION_CUE = "(the conversation continues)"

RETRY_AFTER_TURNS = 2  # turns to wait before retrying a failed condense
MAX_SHRINK_PASSES = 3  # how many times an over-long summary is re-summarized
SHRINK_TARGET = 0.8    # each pass aims below the limit, so the next update has room

_PREAMBLE = re.compile(r"^\s*here('s| is| are)[^\n]*:\s*\n", re.IGNORECASE)
# Everything after the last sentence end or line break (a cut-off fragment).
_INCOMPLETE_TAIL = re.compile(r"[^.!?\u2026\n]*$")


@dataclass
class Turn:
    speaker: str
    text: str


def _trim_to_words(text, limit):
    """Last resort: keep whole lines from the top until the limit is reached."""
    kept, count = [], 0
    for line in text.splitlines():
        n = len(line.split())
        if count + n > limit:
            break
        kept.append(line)
        count += n
    if kept:
        return "\n".join(kept).rstrip()
    cut = " ".join(text.split()[:limit])  # a single enormous line
    return _INCOMPLETE_TAIL.sub("", cut).rstrip() or cut


class Summarizer:
    def __init__(self, client, model, max_words, temperature, first_person=True):
        self.client = client
        self.model = model
        self.max_words = max_words
        self.temperature = temperature
        self.first_person = first_person

    def _clean(self, result):
        text = _PREAMBLE.sub("", result.text).strip()
        if result.truncated:
            # Hit the token limit mid-sentence: keep only the complete part, so a
            # broken fragment never gets stored and fed into every later summary.
            text = _INCOMPLETE_TAIL.sub("", text).rstrip()
        if not text:
            raise LLMError("summarizer returned nothing usable")
        return text

    def condense(self, previous_summary, turns, owner, partner):
        """New notes for `owner` (whose notebook this is) about their talk with `partner`."""
        transcript = "\n".join(f"{t.speaker}: {t.text}" for t in turns)
        messages = build_summarizer_messages(
            previous_summary, transcript, self.max_words, owner, partner,
            self.first_person,
        )
        result = self.client.chat(
            self.model,
            messages,
            temperature=self.temperature,
            # Generous: an over-long summary gets compressed below, so it's better
            # to let the model finish than to cut it off mid-thought.
            max_tokens=int(self.max_words * 3),
        )
        return self._fit(self._clean(result), owner, partner)

    def _fit(self, text, owner, partner):
        """If the notes came back over the limit, summarize the notes themselves
        into something smaller (up to a few passes). Never rejects: if compressing
        fails or makes no progress, the notes are trimmed instead."""
        for attempt in range(1, MAX_SHRINK_PASSES + 1):
            words = len(text.split())
            if words <= self.max_words:
                return text
            print(f"  [summary is {words} words (limit {self.max_words}); "
                  f"compressing, pass {attempt}]")
            try:
                result = self.client.chat(
                    self.model,
                    build_shrink_messages(
                        text, int(self.max_words * SHRINK_TARGET), owner, partner,
                        self.first_person,
                    ),
                    temperature=self.temperature,
                    max_tokens=int(self.max_words * 2),
                )
                shorter = self._clean(result)
            except LLMError as e:
                print(f"  [compressing failed: {e}]")
                break
            if len(shorter.split()) >= words:
                break  # no progress; more passes would just repeat this
            text = shorter
        if len(text.split()) > self.max_words:
            print(f"  [still over the limit; trimming to {self.max_words} words]")
            text = _trim_to_words(text, self.max_words)
        return text


class ConversationMemory:
    def __init__(self, summarizer, max_recent_turns, condense_batch, names, stats=None):
        """`names` are the two speakers; each gets their own summary. `stats`,
        if given, is a stats.RunStats that gets a few counters incremented
        (summarizer_failures, memory_condenses, memory_forced_drops); nothing
        else here depends on it."""
        if condense_batch >= max_recent_turns:
            raise ValueError("CONDENSE_BATCH must be smaller than MAX_RECENT_TURNS")
        if len(names) != 2:
            raise ValueError("ConversationMemory needs exactly two names")
        self.summarizer = summarizer
        self.max_recent = max_recent_turns
        self.batch = condense_batch
        self.names = list(names)
        self.summaries = {n: "" for n in self.names}
        self.recent = []
        self._pending = {}  # new summaries finished before the other one failed
        self._skip = 0
        self.stats = stats

    def summary_for(self, name):
        """`name`'s own notes on the older conversation."""
        return self.summaries.get(name, "")

    def add(self, turn):
        """Record a turn. Returns True if the summaries were just updated."""
        self.recent.append(turn)
        if len(self.recent) < self.max_recent:
            return False

        if self._skip:
            self._skip -= 1  # waiting a few turns after a failed attempt
        elif self._condense():
            return True
        else:
            self._skip = RETRY_AFTER_TURNS

        # If condensing keeps failing, don't let the verbatim window grow forever.
        if len(self.recent) > self.max_recent * 2:
            print(
                f"  [summarizer keeps failing: dropping {self.batch} old turns "
                "without summarizing them]"
            )
            del self.recent[: self.batch]
            self._pending.clear()  # those results were for the turns just dropped
            if self.stats:
                self.stats.memory_forced_drops += 1
        return False

    def _condense(self):
        """Update both people's notes from the same old turns. Nothing is committed
        unless both succeed, so the old turns are never folded in twice."""
        old = self.recent[: self.batch]
        for owner in self.names:
            if owner in self._pending:
                continue  # finished on an earlier attempt
            partner = self.names[1] if owner == self.names[0] else self.names[0]
            try:
                self._pending[owner] = self.summarizer.condense(
                    self.summaries[owner], old, owner, partner
                )
            except LLMError as e:
                print(f"  [summarizer failed for {owner}: {e}; "
                      f"retrying in {RETRY_AFTER_TURNS} turns]")
                if self.stats:
                    self.stats.summarizer_failures += 1
                return False
        self.summaries.update(self._pending)
        self._pending = {}
        del self.recent[: self.batch]
        if self.stats:
            self.stats.memory_condenses += 1
        return True

    def chat_view(self, speaker_name):
        """Recent turns from one speaker's point of view (own lines = assistant)."""
        messages = [
            {"role": "assistant" if t.speaker == speaker_name else "user", "content": t.text}
            for t in self.recent
        ]
        if messages and messages[0]["role"] == "assistant":
            messages.insert(0, {"role": "user", "content": CONTINUATION_CUE})
        return messages
