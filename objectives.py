"""What a person is trying to get out of the conversation.

Each speaker is assigned their own objective, so the two can differ: one can be
digging for information while the other is hiding something. An objective is
the last thing in the system prompt, where it has the most pull on a small
model, and its `reminder` is attached to the last user message of every single
request (never stored in the transcript or the memory).

An objective says nothing about the setting -- that's a scenario (see
scenarios.py). Edit objectives.md to change or add objectives.
"""

from dataclasses import dataclass

import catalog
import config

REQUIRED_SECTIONS = ("goal",)


@dataclass(frozen=True)
class Objective:
    name: str
    goal: str            # the block that goes last in the system prompt
    tagline: str = ""    # one line for the selection menu
    reminder: str = ""   # private per-request nudge; optional
    notes: str = ""      # extra headings for this person's memory; optional

    def goal_for(self, speaker, partner):
        return catalog.fill(
            self.goal, f"Objective '{self.name}'", speaker=speaker, partner=partner
        )

    def reminder_for(self, speaker, partner):
        if not self.reminder:
            return ""
        return catalog.fill(
            self.reminder, f"Objective '{self.name}' reminder",
            speaker=speaker, partner=partner,
        )

    def notes_for(self, owner, partner):
        """Extra memory headings for the person holding this objective, indented
        to sit under the standard ones. `{owner}` and `{speaker}` both mean them."""
        if not self.notes:
            return ""
        filled = catalog.fill(
            self.notes, f"Objective '{self.name}' notes",
            owner=owner, speaker=owner, partner=partner,
        )
        return "\n".join(
            "  " + line.strip() for line in filled.splitlines() if line.strip()
        )


def load_objectives(path=None):
    """Parse objectives.md into a list of Objective, in file order."""
    entries = catalog.load(
        path or config.OBJECTIVES_PATH, REQUIRED_SECTIONS, "objective"
    )
    return [
        Objective(
            name=name,
            goal=s["goal"],  # paragraphs and lists are kept as written
            tagline=catalog.collapse(s.get("tagline", "")),
            reminder=catalog.collapse(s.get("reminder", "")),
            notes=s.get("notes", ""),  # one heading per line, kept as written
        )
        for name, s in entries
    ]
