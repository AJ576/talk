"""Loads the personas from personas.md and sets the scene.

Edit personas.md to change or add people. Neither persona is ever told that the
other is an AI: to each of them, the other is just a friend.
"""

from dataclasses import dataclass
from pathlib import Path

import config

REQUIRED_SECTIONS = ("bio", "style")


@dataclass(frozen=True)
class Persona:
    name: str      # short name used in the transcript
    bio: str       # who they are
    style: str     # how they talk
    tagline: str = ""  # one line for the selection menu


def _resolve(path):
    p = Path(path)
    return p if p.is_absolute() else Path(__file__).parent / p


def load_personas(path=None):
    """Parse personas.md into a list of Persona, in file order.
    Unknown sections are ignored."""
    path = _resolve(path or config.PERSONAS_PATH)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Could not read personas file {path}: {e}") from e

    raw = {}  # name -> {section: [lines]}
    name = section = None
    for line in text.splitlines():
        if line.startswith("### ") and name:
            section = line[4:].strip().lower()
            raw[name][section] = []
        elif line.startswith("## "):
            name = line[3:].strip()
            raw[name] = {}
            section = None
        elif name and section:
            raw[name][section].append(line)

    personas = []
    for pname, sections in raw.items():
        joined = {k: " ".join(" ".join(v).split()) for k, v in sections.items()}
        missing = [s for s in REQUIRED_SECTIONS if not joined.get(s)]
        if missing:
            raise ValueError(
                f"Persona '{pname}' in {path.name} is missing: {', '.join(missing)}"
            )
        personas.append(
            Persona(
                name=pname,
                bio=joined["bio"],
                style=joined["style"],
                tagline=joined.get("tagline", ""),
            )
        )
    if len(personas) < 2:
        raise ValueError(f"{path.name} needs at least two personas")
    return personas


def find_persona(personas, name):
    """Case-insensitive lookup; returns None if there's no match."""
    for p in personas:
        if p.name.lower() == name.strip().lower():
            return p
    return None


# {partner} is the other person's name, {place} is "your place" or "<Host>'s place".
SCENARIO = (
    "You and {partner} are talking. "
)

# Shown only to the host, on the very first turn.
OPENER = (
    "(You've just started talking with {partner},"
    "Start the conversation in your own way."
)


def build_scenario(speaker, partner, host):
    """The scene as seen by `speaker`. The scene is at the host's home."""
    if speaker.name == host.name:
        place = "your place"
    else:
        place = f"{host.name}'s place"
    return SCENARIO.format(partner=partner.name, place=place)