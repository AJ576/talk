"""Conversation memory: recent turns verbatim + a rolling condensed summary.

The Summarizer is a separate model that never sees the live conversation. It is
only ever handed "old notes + a chunk of old transcript" and returns new notes.
"""

import re
from dataclasses import dataclass

from llm import LLMError
from prompts import build_summarizer_messages

# Used when the verbatim window happens to begin with the speaker's own line,
# because most chat models expect the first message to come from the "user".
CONTINUATION_CUE = "(the conversation continues)"

RETRY_AFTER_TURNS = 2  # turns to wait before retrying a failed condense
MAX_OVERSHOOT = 1.5    # a summary this many times over the word limit is rejected

_PREAMBLE = re.compile(r"^\s*here('s| is| are)[^\n]*:\s*\n", re.IGNORECASE)
# Everything after the last sentence end or line break (a cut-off fragment).
_INCOMPLETE_TAIL = re.compile(r"[^.!?\u2026\n]*$")


@dataclass
class Turn:
    speaker: str
    text: str


class Summarizer:
    def __init__(self, client, model, max_words, temperature):
        self.client = client
        self.model = model
        self.max_words = max_words
        self.temperature = temperature

    def condense(self, previous_summary, turns):
        transcript = "\n".join(f"{t.speaker}: {t.text}" for t in turns)
        messages = build_summarizer_messages(previous_summary, transcript, self.max_words)
        result = self.client.chat(
            self.model,
            messages,
            temperature=self.temperature,
            max_tokens=int(self.max_words * 2),  # ~1.4 tokens/word, with headroom
        )
        text = _PREAMBLE.sub("", result.text).strip()

        if result.truncated:
            # Hit the token limit mid-sentence: keep only the complete part, so a
            # broken fragment never gets stored and fed into every later summary.
            text = _INCOMPLETE_TAIL.sub("", text).rstrip()
        if not text:
            raise LLMError("summarizer returned nothing usable")

        words = len(text.split())
        if words > self.max_words * MAX_OVERSHOOT:
            raise LLMError(
                f"summary came back at {words} words (limit {self.max_words})"
            )
        return text


class ConversationMemory:
    def __init__(self, summarizer, max_recent_turns, condense_batch):
        if condense_batch >= max_recent_turns:
            raise ValueError("CONDENSE_BATCH must be smaller than MAX_RECENT_TURNS")
        self.summarizer = summarizer
        self.max_recent = max_recent_turns
        self.batch = condense_batch
        self.summary = ""
        self.recent = []
        self._skip = 0

    def add(self, turn):
        """Record a turn. Returns True if the summary was just updated."""
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
        return False

    def _condense(self):
        try:
            updated = self.summarizer.condense(self.summary, self.recent[: self.batch])
        except LLMError as e:
            print(f"  [summarizer failed: {e}; retrying in {RETRY_AFTER_TURNS} turns]")
            return False
        self.summary = updated
        del self.recent[: self.batch]
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