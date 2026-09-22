"""Where the two people are and how they came to be talking.

A scenario is pure setting. It says nothing about what either person is trying
to do in the conversation -- that's an objective (see objectives.py). The two
are chosen independently, so any scenario can be run with any pair of
objectives.

Edit scenarios.md to change or add settings.
"""

from dataclasses import dataclass

import catalog
import config

REQUIRED_SECTIONS = ("setting", "opener")


@dataclass(frozen=True)
class Scenario:
    name: str
    setting: str        # the scene, shown to both people
    opener: str         # turn-0 instruction, shown only to the first speaker
    tagline: str = ""   # one line for the selection menu
    first: str = ""     # extra line only the first speaker sees (e.g. "you're hosting")
    second: str = ""    # extra line only the second speaker sees (e.g. "you're the guest")
    knowledge: str = "" # what they may assume they already know about each other

    def setting_for(self, speaker, partner, is_first):
        """The scene as `speaker` sees it. `is_first` picks the side-specific
        line, so a scenario with roles (host/guest) can tell them apart."""
        parts = [self.setting, self.first if is_first else self.second, self.knowledge]
        return " ".join(
            catalog.fill(p, f"Scenario '{self.name}'", speaker=speaker, partner=partner)
            for p in parts if p
        )

    def opener_for(self, speaker, partner):
        return catalog.fill(
            self.opener, f"Scenario '{self.name}' opener", speaker=speaker, partner=partner
        )


def load_scenarios(path=None):
    """Parse scenarios.md into a list of Scenario, in file order."""
    entries = catalog.load(
        path or config.SCENARIOS_PATH, REQUIRED_SECTIONS, "scenario"
    )
    return [
        Scenario(
            name=name,
            setting=catalog.collapse(s["setting"]),
            opener=catalog.collapse(s["opener"]),
            tagline=catalog.collapse(s.get("tagline", "")),
            first=catalog.collapse(s.get("first", "")),
            second=catalog.collapse(s.get("second", "")),
            knowledge=catalog.collapse(s.get("knowledge", "")),
        )
        for name, s in entries
    ]
