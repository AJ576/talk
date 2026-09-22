"""Shared loader for the markdown catalogues: personas, scenarios, objectives.

All three files have the same shape:

    ## Name
    ### section
    text, possibly several paragraphs
    ### another section
    text

`## ` starts a new entry, `### ` starts a section inside it, and everything
else is body text for the section currently open. Sections the code doesn't
know about are ignored, so a file can carry notes and headings for the reader.

Blank lines inside a section are kept, because an objective's text is written
as paragraphs and a numbered list. Loaders that want a single line (a tagline,
a bio) call `collapse` themselves.
"""

from pathlib import Path


def resolve(path):
    """Relative paths are resolved next to the scripts, not the shell's cwd."""
    p = Path(path)
    return p if p.is_absolute() else Path(__file__).parent / p


def collapse(text):
    """All whitespace, including newlines, squeezed down to single spaces."""
    return " ".join(text.split())


def parse(text):
    """[(name, {section: text})] in file order. A name repeated later in the
    file adds to the first block rather than silently replacing it."""
    entries = {}
    order = []
    name = section = None
    for line in text.splitlines():
        if line.startswith("### ") and name:
            section = line[4:].strip().lower()
            entries[name].setdefault(section, [])
        elif line.startswith("## "):
            name = line[3:].strip()
            if name not in entries:
                entries[name] = {}
                order.append(name)
            section = None
        elif name and section:
            entries[name][section].append(line)
    return [
        (name, {s: "\n".join(lines).strip() for s, lines in entries[name].items()})
        for name in order
    ]


def load(path, required, kind, minimum=1):
    """Read and parse a catalogue file. `required` sections must be present and
    non-empty on every entry; `kind` only shapes the error messages."""
    path = resolve(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Could not read {kind} file {path}: {e}") from e

    entries = parse(text)
    for name, sections in entries:
        missing = [s for s in required if not sections.get(s)]
        if missing:
            raise ValueError(
                f"{kind.capitalize()} '{name}' in {path.name} is missing: "
                + ", ".join(missing)
            )
    if len(entries) < minimum:
        raise ValueError(f"{path.name} needs at least {minimum} {kind}(s)")
    return entries


def find(items, name):
    """Case-insensitive lookup by `.name`; None if there's no match."""
    if name is None:
        return None
    wanted = name.strip().lower()
    for item in items:
        if item.name.lower() == wanted:
            return item
    return None


def fill(template, where, **values):
    """`str.format` with a readable error when a catalogue entry contains a
    placeholder nobody supplies (a stray brace, or a typo like {partner_name}).
    `where` names the entry, for the message; it is positional so that a
    placeholder can be called `where` too."""
    try:
        return template.format(**values)
    except (KeyError, IndexError) as e:
        known = ", ".join("{" + k + "}" for k in values)
        raise ValueError(
            f"{where} uses an unknown placeholder {e}; only {known} are available. "
            "Write a literal brace as {{ or }}."
        ) from e
