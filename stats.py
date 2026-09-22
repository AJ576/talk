"""A tiny run summary, written to JSON as the run progresses.

Nothing here affects the conversation. It only counts things that already
happen (turns, retries, failures) so a long unattended run can be checked on
without reading the whole transcript. Overwritten in place on every update --
this is a snapshot of "where things stand", not an append-only log.
"""

import json
from dataclasses import asdict, dataclass, field

from storage import stamp


@dataclass
class RunStats:
    speaker_a: str = ""
    speaker_b: str = ""
    model_a: str = ""
    model_b: str = ""
    summarizer_model: str = ""
    script_mode: bool = False
    scenario: str = ""           # the setting this run was given
    objective_a: str = ""        # what speaker_a is trying to do
    objective_b: str = ""        # what speaker_b is trying to do
    started_at: str = field(default_factory=stamp)
    updated_at: str = ""

    turns_completed: int = 0
    empty_replies: int = 0
    llm_errors: int = 0          # retryable LLMErrors from a speaker call
    fatal_error: str = ""        # set just before the run stops abnormally

    repetition_regenerations: int = 0  # extra attempts beyond the first, summed
    repetition_still_over_limit: int = 0  # replies kept despite being over REPEAT_MAX_OVERLAP

    memory_condenses: int = 0          # successful two-person condense passes
    summarizer_failures: int = 0       # failed condense() calls (either person)
    memory_forced_drops: int = 0       # old turns dropped without summarizing

    def to_dict(self):
        return asdict(self)


class StatsLog:
    """Holds a RunStats and writes it to `path` as plain JSON on every update.
    Safe to call `write` often; it's a small file and each write replaces the
    last one."""

    def __init__(self, path, stats=None):
        self.path = path
        self.stats = stats or RunStats()

    def write(self):
        self.stats.updated_at = stamp()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.stats.to_dict(), f, indent=2)
            f.write("\n")
