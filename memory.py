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

_PREAMBLE = re.compile(r"^\s*here('s| is| are)[^\n]*:\s*\n", re.IGNORECASE)


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
        result = self.client.chat(self.model, messages, temperature=self.temperature)
        return _PREAMBLE.sub("", result).strip()


class ConversationMemory:
    def __init__(self, summarizer, max_recent_turns, condense_batch):
        if condense_batch >= max_recent_turns:
            raise ValueError("CONDENSE_BATCH must be smaller than MAX_RECENT_TURNS")
        self.summarizer = summarizer
        self.max_recent = max_recent_turns
        self.batch = condense_batch
        self.summary = ""
        self.recent = []

    def add(self, turn):
        """Record a turn. Returns True if the summary was just updated."""
        self.recent.append(turn)
        if len(self.recent) < self.max_recent:
            return False

        try:
            updated = self.summarizer.condense(self.summary, self.recent[: self.batch])
        except LLMError as e:
            print(f"  [summarizer failed: {e}]")
            updated = ""

        if not updated:
            # Keep the raw turns and retry next turn, but never grow forever.
            if len(self.recent) > self.max_recent * 2:
                del self.recent[: self.batch]
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
