"""The main loop: alternate speakers, feed each their memory, log everything."""

import re
import time

import config
from llm import LLMError
from memory import Turn
from prompts import build_speaker_prompt
from storage import stamp

# Filler openers that make two models spiral into mutual flattery. Only matched
# when followed by punctuation, so "Absolutely not, because..." keeps its meaning.
_FILLER_OPENER = re.compile(
    r"^(?:(?:ah|oh|ha)[,!.]?\s+)?(?:exactly|absolutely|precisely|totally|definitely|indeed)\s*[,!.\u2014]+\s*"
    r"|^(?:ah|oh)[,!.]?\s+(?:yes|yeah)\s*[,!.\u2014]+\s*",
    re.IGNORECASE,
)
_PRAISE = re.compile(
    r"(?:^|(?<=[.!?] ))(?:and |but )?i (?:really |just )?love (?:what|how|the way|that) you[^.!?]*[.!?]\s*",
    re.IGNORECASE | re.MULTILINE,
)


def clean_reply(text, name, truncated=False):
    """Strip habits models fall into: 'Name:' prefixes, filler agreement openers,
    praise for the other person, and wrapping quotes. Actions like *sighs* and
    (laughs) are left alone.

    `truncated` says the model hit the token limit; only then is a dangling
    half-sentence at the end dropped."""
    text = text.strip()
    text = re.sub(rf"^{re.escape(name)}\s*:\s*", "", text, flags=re.IGNORECASE)

    for _ in range(3):
        stripped = _FILLER_OPENER.sub("", text, count=1).strip()
        if not stripped or stripped == text:
            break  # nothing left to strip (or it would erase the whole reply)
        text = stripped

    text = (_PRAISE.sub("", text).strip()) or text
    text = text[:1].upper() + text[1:]
    if len(text) > 1 and text[0] == '"' and text[-1] == '"' and text.count('"') == 2:
        text = text[1:-1].strip()  # the whole reply was wrapped in quotes
    text = re.sub(r"[ \t]+", " ", text).strip()
    return _drop_cut_off_tail(text) if truncated else text


# A reply ends cleanly on sentence punctuation (optionally followed by a closing
# quote/bracket/asterisk) or on a finished *action*.
_ENDS_CLEANLY = re.compile(r"(?:[.!?\u2026][\"')\]*]*|\*[^*\n]{1,80}\*)$")
_TRAILING_FRAGMENT = re.compile(r"^(.*[.!?\u2026][\"')\]*]*)\s+[^.!?\u2026]*$", re.DOTALL)


def _drop_cut_off_tail(text):
    """Keep only the complete sentences of a reply that was cut off by the token limit."""
    if not text or _ENDS_CLEANLY.search(text):
        return text
    m = _TRAILING_FRAGMENT.match(text)
    return m.group(1) if m else text


class Conversation:
    def __init__(
        self, client, models, personas, memory, scenario_fn, opener,
        transcript_log, memory_log,
    ):
        self.client = client
        self.models = models              # models[i] plays personas[i]
        self.personas = personas          # personas[0] is the host and speaks first
        self.memory = memory
        self.scenario_fn = scenario_fn    # (speaker, partner) -> scene text
        self.opener = opener              # contains {partner}
        self.transcript_log = transcript_log  # append-only: every message
        self.memory_log = memory_log          # append-only: every summary update

    def run(self):
        a, b = self.personas
        header = f"=== New session | {stamp()} | {a.name} (host) & {b.name} ===\n\n"
        self.transcript_log.write("\n" + header)
        self.memory_log.write("\n" + header)

        turn_no = 0
        empty_streak = 0
        error_streak = 0

        while config.MAX_TURNS is None or turn_no < config.MAX_TURNS:
            idx = turn_no % 2
            speaker = self.personas[idx]
            partner = self.personas[1 - idx]

            system = build_speaker_prompt(
                speaker, partner.name, self.scenario_fn(speaker, partner),
                self.memory.summary,
            )
            history = self.memory.chat_view(speaker.name) or [
                {"role": "user", "content": self.opener.format(partner=partner.name)}
            ]

            print(f"{speaker.name}: ", end="", flush=True)
            try:
                reply = self.client.chat(
                    self.models[idx],
                    [{"role": "system", "content": system}] + history,
                    temperature=config.SPEAKER_TEMPERATURE,
                    max_tokens=config.REPLY_MAX_TOKENS,
                    on_token=lambda t: print(t, end="", flush=True),
                )
            except LLMError as e:
                error_streak += 1
                if not e.retryable or error_streak >= config.MAX_CONSECUTIVE_ERRORS:
                    raise
                print(
                    f"\n  [{e}]\n  [retrying in {config.RETRY_WAIT_SECONDS}s "
                    f"({error_streak}/{config.MAX_CONSECUTIVE_ERRORS})]\n"
                )
                time.sleep(config.RETRY_WAIT_SECONDS)
                continue
            error_streak = 0
            print("\n")

            text = clean_reply(reply.text, speaker.name, reply.truncated)
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