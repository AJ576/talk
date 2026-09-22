"""Loads the people from personas.md.

A persona is only ever who someone is and how they talk. Where they are comes
from a scenario (scenarios.py) and what they want comes from an objective
(objectives.py), so the same person can be dropped into any setting with any
agenda.
"""

from dataclasses import dataclass

import catalog
import config

REQUIRED_SECTIONS = ("bio", "style")


@dataclass(frozen=True)
class Persona:
    name: str      # short name used in the transcript
    bio: str       # who they are
    style: str     # how they talk
    tagline: str = ""  # one line for the selection menu


def load_personas(path=None):
    """Parse personas.md into a list of Persona, in file order."""
    entries = catalog.load(
        path or config.PERSONAS_PATH, REQUIRED_SECTIONS, "persona", minimum=2
    )
    return [
        Persona(
            name=name,
            bio=catalog.collapse(s["bio"]),
            style=catalog.collapse(s["style"]),
            tagline=catalog.collapse(s.get("tagline", "")),
        )
        for name, s in entries
    ]


def find_persona(personas, name):
    """Case-insensitive lookup; returns None if there's no match."""
    return catalog.find(personas, name)
