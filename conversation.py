"""The main loop: alternate speakers, feed each their memory, log everything."""

import re
import time

import config
from llm import LLMError
from memory import Turn
from prompts import (
    REPEAT_NUDGE,
    add_reminder,
    build_script_message,
    build_speaker_prompt,
)
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


_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")   # **emphasis** -> emphasis
_ACTION = re.compile(r"\*[^*\n]+\*")        # *sighs*, *leans back and laughs*
_OPEN_ACTION = re.compile(r"\*[^*\n]*$")     # *sighs   (cut off before the closing *)


def strip_actions(text, truncated=False):
    """Remove *action* stage directions and any stray asterisks. **Bold** is
    unwrapped, not deleted. A single *emphasized* word is removed too, because
    it looks exactly like an action.

    `truncated` says the model hit the token limit. Only then is an unclosed
    `*...` at the end treated as an action cut off mid-word and dropped. In a
    reply the model chose to end, a lone asterisk is just a stray character
    ("it cost 5 * 3 dollars"), and deleting everything after it would throw
    away real content."""
    text = _BOLD.sub(r"\1", text)
    cleaned = _ACTION.sub("", text)
    if truncated:
        cleaned = _OPEN_ACTION.sub("", cleaned)
    cleaned = cleaned.replace("*", "")
    if cleaned == text:
        return text
    cleaned = re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)  # "well , fine" -> "well, fine"
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.lstrip(" ,;:").strip()


_MAX_PREFIX_STRIPS = 3  # models sometimes stack them: "Lena: Lena: hi"


def _partner_cut(text, partner):
    """Where the model stopped being itself and started writing `partner`'s line.
    Returns the part before that, or "" if it never did. The label has to open a
    new line or a new sentence, so "I told Dev: bring wine" is left alone."""
    m = re.search(
        rf"(?:\n\s*|(?<=[.!?\u2026])\s+){re.escape(partner)}\s*:",
        text, flags=re.IGNORECASE,
    )
    return text[: m.start()].strip() if m else ""


def clean_reply(text, name, truncated=False, partner=None):
    """Strip habits models fall into: 'Name:' prefixes, *action* stage directions,
    filler agreement openers, praise for the other person, and wrapping quotes.
    If `partner` is given, anything from the point where "Partner:" opens a new
    line or sentence is cut (a script-mode model writing the other side).

    `truncated` says the model hit the token limit; only then is a dangling
    half-sentence at the end dropped."""
    # Actions come off first, so "*nods* Exactly, ..." is caught by the opener
    # check below and "*smiles* Lena: hi" still loses its name prefix.
    text = strip_actions(text.strip(), truncated)
    if partner:
        text = _partner_cut(text, partner) or text
    for _ in range(_MAX_PREFIX_STRIPS):
        stripped = re.sub(rf"^{re.escape(name)}\s*:\s*", "", text, count=1,
                          flags=re.IGNORECASE)
        if stripped == text:
            break
        text = stripped

    for _ in range(3):
        stripped = _FILLER_OPENER.sub("", text, count=1).strip()
        if not stripped or stripped == text:
            break  # nothing left to strip (or it would erase the whole reply)
        text = stripped

    text = (_PRAISE.sub("", text).strip()) or text
    if len(text) > 1 and text[0] == '"' and text[-1] == '"' and text.count('"') == 2:
        text = text[1:-1].strip()  # the whole reply was wrapped in quotes
    text = text[:1].upper() + text[1:]  # after unwrapping, so '"this..."' gets it too
    text = re.sub(r"[ \t]+", " ", text).strip()
    return _drop_cut_off_tail(text) if truncated else text


# A reply ends cleanly on sentence punctuation (optionally followed by a closing
# quote or bracket).
_ENDS_CLEANLY = re.compile(r"[.!?\u2026][\"')\]]*$")
_TRAILING_FRAGMENT = re.compile(r"^(.*[.!?\u2026][\"')\]*]*)\s+[^.!?\u2026]*$", re.DOTALL)


def _drop_cut_off_tail(text):
    """Keep only the complete sentences of a reply that was cut off by the token limit."""
    if not text or _ENDS_CLEANLY.search(text):
        return text
    m = _TRAILING_FRAGMENT.match(text)
    return m.group(1) if m else text


# Empty replies in a row before the run gives up (the error limit lives in
# config; this one is a hard stop for a model that has stopped producing text).
MAX_CONSECUTIVE_EMPTY = 3


def _phrases(text, n=4):
    words = re.findall(r"[a-z']+", text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def repetition_score(text, recent_texts):
    """Share (0..1) of this reply's 4-word phrases that already appeared in the
    recent messages, by either speaker. Very short replies score 0."""
    mine = _phrases(text)
    if len(mine) < 8:
        return 0.0
    seen = set()
    for t in recent_texts:
        seen |= _phrases(t)
    return len(mine & seen) / len(mine)


class Conversation:
    def __init__(
        self, client, models, personas, objectives, memory, scenario,
        transcript_log, memory_log, stats_log=None,
    ):
        self.client = client
        self.models = models              # models[i] plays personas[i]
        self.personas = personas          # personas[0] speaks first
        self.objectives = objectives      # objectives[i] is what personas[i] wants
        self.memory = memory
        self.scenario = scenario          # scenarios.Scenario: the shared setting
        self.transcript_log = transcript_log  # append-only: every message
        self.memory_log = memory_log          # append-only: every summary update
        self.stats_log = stats_log            # optional stats.StatsLog; written each turn

    def _generate(self, idx, speaker, partner, system, history):
        """Produce one cleaned reply. If it reuses too much recent wording, try
        again (nudged, slightly hotter) and keep the least repetitive attempt."""
        enabled = config.REPEAT_REMOVER
        recent = [t.text for t in self.memory.recent[-config.REPEAT_CHECK_TURNS:]]
        if enabled:
            options = {
                "repeat_penalty": config.REPEAT_PENALTY,
                "repeat_last_n": config.REPEAT_LAST_N,
            }
        else:
            options = {"repeat_penalty": 1.0}  # 1.0 = no penalty at all
        max_retries = config.REPEAT_MAX_RETRIES if enabled else 0
        if config.SCRIPT_MODE:
            # Don't let the model carry on and write the other person's lines.
            options["stop"] = [f"\n{partner.name}:"]
        temperature = config.SPEAKER_TEMPERATURE
        best_text, best_score = "", 2.0

        for attempt in range(max_retries + 1):
            prompt = system if attempt == 0 else system + "\n\n" + REPEAT_NUDGE
            label = speaker.name if attempt == 0 else f"{speaker.name} (retry {attempt})"
            print(f"{label}: ", end="", flush=True)
            reply = self.client.chat(
                self.models[idx],
                [{"role": "system", "content": prompt}] + history,
                temperature=temperature,
                max_tokens=config.REPLY_MAX_TOKENS,
                on_token=lambda t: print(t, end="", flush=True),
                extra_options=options,
            )
            print("\n")

            text = clean_reply(reply.text, speaker.name, reply.truncated, partner.name)
            if not text:
                return best_text  # empty; the caller counts these
            if not enabled:
                return text
            score = repetition_score(text, recent)
            if score < best_score:
                best_text, best_score = text, score
            if score <= config.REPEAT_MAX_OVERLAP:
                return text
            if attempt < max_retries:
                print(f"  [{score:.0%} of that reused recent wording; trying again]\n")
                temperature = min(temperature + 0.1, 1.3)
                if self.stats_log:
                    self.stats_log.stats.repetition_regenerations += 1
        if enabled and self.stats_log:
            self.stats_log.stats.repetition_still_over_limit += 1
        return best_text

    def run(self):
        a, b = self.personas
        header = (
            f"=== New session | {stamp()} | {a.name} & {b.name} "
            f"| {self.scenario.name} "
            f"| {self.objectives[0].name} vs {self.objectives[1].name} ===\n\n"
        )
        self.transcript_log.write("\n" + header)
        self.memory_log.write("\n" + header)

        turn_no = 0
        empty_streak = 0
        error_streak = 0

        while config.MAX_TURNS is None or turn_no < config.MAX_TURNS:
            idx = turn_no % 2
            speaker = self.personas[idx]
            partner = self.personas[1 - idx]
            objective = self.objectives[idx]

            # Each speaker gets their own side of the setting, their own memory
            # of the older conversation, and their own objective.
            system = build_speaker_prompt(
                speaker, partner.name,
                self.scenario.setting_for(speaker.name, partner.name, idx == 0),
                self.memory.summary_for(speaker.name),
                objective.goal_for(speaker.name, partner.name),
            )
            if not self.memory.recent:
                opener = self.scenario.opener_for(speaker.name, partner.name)
                history = [{"role": "user", "content": opener}]
            elif config.SCRIPT_MODE:
                history = [{
                    "role": "user",
                    "content": build_script_message(
                        self.memory.recent, speaker.name, partner.name
                    ),
                }]
            else:
                history = self.memory.chat_view(speaker.name)
            # A private nudge on the last user message of this one request only:
            # it is never written to the transcript or folded into memory, so
            # the other speaker never learns what this one is trying to do.
            history = add_reminder(
                history, objective.reminder_for(speaker.name, partner.name)
            )

            try:
                text = self._generate(idx, speaker, partner, system, history)
            except LLMError as e:
                error_streak += 1
                if self.stats_log:
                    self.stats_log.stats.llm_errors += 1
                if not e.retryable or error_streak >= config.MAX_CONSECUTIVE_ERRORS:
                    if self.stats_log:
                        self.stats_log.stats.fatal_error = str(e)
                        self.stats_log.write()
                    raise
                print(
                    f"\n  [{e}]\n  [retrying in {config.RETRY_WAIT_SECONDS}s "
                    f"({error_streak}/{config.MAX_CONSECUTIVE_ERRORS})]\n"
                )
                if self.stats_log:
                    self.stats_log.write()
                time.sleep(config.RETRY_WAIT_SECONDS)
                continue
            error_streak = 0

            if not text:
                empty_streak += 1
                if self.stats_log:
                    self.stats_log.stats.empty_replies += 1
                if empty_streak >= MAX_CONSECUTIVE_EMPTY:
                    message = (
                        f"A model returned empty replies {MAX_CONSECUTIVE_EMPTY} "
                        "times in a row."
                    )
                    if self.stats_log:
                        self.stats_log.stats.fatal_error = message
                        self.stats_log.write()
                    raise RuntimeError(message)
                # Retrying instantly would almost certainly produce another
                # empty reply, so wait as long as a failed request does.
                print(
                    f"\n  [{speaker.name} returned nothing usable]\n"
                    f"  [retrying in {config.RETRY_WAIT_SECONDS}s "
                    f"({empty_streak}/{MAX_CONSECUTIVE_EMPTY})]\n"
                )
                if self.stats_log:
                    self.stats_log.write()
                time.sleep(config.RETRY_WAIT_SECONDS)
                continue
            empty_streak = 0

            # Written to disk the moment the message is complete.
            self.transcript_log.write(f"{speaker.name}: {text}\n\n")
            turn_no += 1
            if self.stats_log:
                self.stats_log.stats.turns_completed = turn_no

            if self.memory.add(Turn(speaker.name, text)):
                sizes = ", ".join(
                    f"{p.name} {len(self.memory.summary_for(p.name).split())} words"
                    for p in self.personas
                )
                print(f"  [memory condensed: {sizes}]\n")
                for p in self.personas:
                    self.memory_log.write(
                        f"--- {p.name}'s memory after message {turn_no} | {stamp()} ---\n"
                        f"{self.memory.summary_for(p.name)}\n\n"
                    )

            if self.stats_log:
                self.stats_log.write()

            if config.TURN_DELAY_SECONDS:
                time.sleep(config.TURN_DELAY_SECONDS)
