"""The main loop: alternate speakers, feed each their memory, log everything."""

import re
import time

import config
from llm import LLMError
from memory import Turn
from prompts import build_speaker_prompt
from storage import stamp

_ACTION = re.compile(r"\*[^*\n]{1,80}\*")


def clean_reply(text, name):
    """Strip things models like to add: 'Name:' prefixes, *actions*, wrapping quotes."""
    text = text.strip()
    text = re.sub(rf"^{re.escape(name)}\s*:\s*", "", text, flags=re.IGNORECASE)
    text = _ACTION.sub("", text)
    text = text.strip()
    if len(text) > 1 and text[0] == '"' and text[-1] == '"' and text.count('"') == 2:
        text = text[1:-1].strip()  # the whole reply was wrapped in quotes
    text = re.sub(r"[ \t]+", " ", text)
    return _drop_cut_off_tail(text)


_ENDS_CLEANLY = re.compile(r"[.!?\u2026][\"')\]]?$")
_TRAILING_FRAGMENT = re.compile(r"^(.*[.!?\u2026][\"')\]]?)\s+[^.!?\u2026]*$", re.DOTALL)


def _drop_cut_off_tail(text):
    """If the token limit cut the reply mid-sentence, keep only the complete sentences."""
    if not text or _ENDS_CLEANLY.search(text):
        return text
    m = _TRAILING_FRAGMENT.match(text)
    return m.group(1) if m else text


class Conversation:
    def __init__(self, client, personas, memory, scenario, opener, transcript_log, memory_log):
        self.client = client
        self.personas = personas
        self.memory = memory
        self.scenario = scenario
        self.opener = opener
        self.transcript_log = transcript_log  # append-only: every message
        self.memory_log = memory_log          # append-only: every summary update

    def run(self):
        header = f"=== New session | {stamp()} ===\n\n"
        self.transcript_log.write("\n" + header)
        self.memory_log.write("\n" + header)

        turn_no = 0
        empty_streak = 0
        error_streak = 0

        while config.MAX_TURNS is None or turn_no < config.MAX_TURNS:
            speaker = self.personas[turn_no % 2]
            partner = self.personas[(turn_no + 1) % 2]

            system = build_speaker_prompt(
                speaker, partner.name, self.scenario, self.memory.summary
            )
            history = self.memory.chat_view(speaker.name) or [
                {"role": "user", "content": self.opener}
            ]

            print(f"{speaker.name}: ", end="", flush=True)
            try:
                raw = self.client.chat(
                    speaker.model,
                    [{"role": "system", "content": system}] + history,
                    temperature=config.SPEAKER_TEMPERATURE,
                    max_tokens=config.REPLY_MAX_TOKENS,
                    on_token=lambda t: print(t, end="", flush=True),
                )
            except LLMError as e:
                error_streak += 1
                if error_streak >= config.MAX_CONSECUTIVE_ERRORS:
                    raise
                print(
                    f"\n  [{e}]\n  [retrying in {config.RETRY_WAIT_SECONDS}s "
                    f"({error_streak}/{config.MAX_CONSECUTIVE_ERRORS})]\n"
                )
                time.sleep(config.RETRY_WAIT_SECONDS)
                continue
            error_streak = 0
            print("\n")

            text = clean_reply(raw, speaker.name)
            if not text:
                empty_streak += 1
                if empty_streak >= 3:
                    raise RuntimeError("A model returned empty replies 3 times in a row.")
                continue
            empty_streak = 0

            # Written to disk the moment the message is complete.
            self.transcript_log.write(f"{speaker.name}: {text}\n\n")
            turn_no += 1

            if self.memory.add(Turn(speaker.name, text)):
                words = len(self.memory.summary.split())
                print(f"  [memory condensed: summary is now {words} words]\n")
                self.memory_log.write(
                    f"--- Memory update after message {turn_no} | {stamp()} ---\n"
                    f"{self.memory.summary}\n\n"
                )

            if config.TURN_DELAY_SECONDS:
                time.sleep(config.TURN_DELAY_SECONDS)