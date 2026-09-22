"""Tests for the catalogue layer: the shared markdown parser, and the three
loaders built on it. The shipped .md files are loaded too, so a broken
placeholder or a missing section in the data is caught here."""

import pytest

import catalog
from objectives import Objective, load_objectives
from personas import load_personas
from scenarios import Scenario, load_scenarios

# ---------------------------------------------------------------------------
# catalog.parse
# ---------------------------------------------------------------------------

SAMPLE = """\
# A title, not an entry

Some prose before the first entry.

## First

### Tagline
short line

### Bio
a first paragraph

a second paragraph

## Second

### Bio
only a bio
"""


def test_parse_returns_entries_in_file_order():
    assert [name for name, _ in catalog.parse(SAMPLE)] == ["First", "Second"]


def test_parse_lowercases_section_names():
    sections = dict(catalog.parse(SAMPLE))["First"]
    assert set(sections) == {"tagline", "bio"}


def test_parse_keeps_blank_lines_inside_a_section():
    bio = dict(catalog.parse(SAMPLE))["First"]["bio"]
    assert bio == "a first paragraph\n\na second paragraph"


def test_parse_ignores_a_single_hash_title():
    assert "A title, not an entry" not in dict(catalog.parse(SAMPLE))


def test_parse_ignores_a_section_before_any_entry():
    assert catalog.parse("### Orphan\ntext\n") == []


def test_parse_merges_a_repeated_name_instead_of_replacing_it():
    text = "## Same\n### Bio\nfirst\n\n## Same\n### Style\nsecond\n"
    entries = catalog.parse(text)
    assert len(entries) == 1
    assert entries[0][1] == {"bio": "first", "style": "second"}


def test_collapse_squeezes_newlines_and_runs_of_spaces():
    assert catalog.collapse("a  b\n\nc\n d") == "a b c d"


# ---------------------------------------------------------------------------
# catalog.load / find / fill
# ---------------------------------------------------------------------------

def write(tmp_path, text, name="cat.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_load_rejects_an_entry_missing_a_required_section(tmp_path):
    path = write(tmp_path, "## Only\n### Bio\nhi\n")
    with pytest.raises(ValueError, match="missing: style"):
        catalog.load(path, ("bio", "style"), "persona")


def test_load_rejects_a_required_section_that_is_empty(tmp_path):
    path = write(tmp_path, "## Only\n### Bio\nhi\n### Style\n\n")
    with pytest.raises(ValueError, match="missing: style"):
        catalog.load(path, ("bio", "style"), "persona")


def test_load_enforces_a_minimum_number_of_entries(tmp_path):
    path = write(tmp_path, "## Only\n### Bio\nhi\n")
    with pytest.raises(ValueError, match="at least 2"):
        catalog.load(path, ("bio",), "persona", minimum=2)


def test_load_reports_a_missing_file_as_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="Could not read"):
        catalog.load(tmp_path / "nope.md", (), "persona")


def test_find_is_case_and_space_insensitive():
    items = load_scenarios()
    assert catalog.find(items, "  ONLINE ").name == "online"
    assert catalog.find(items, "nope") is None
    assert catalog.find(items, None) is None


def test_fill_names_the_entry_when_a_placeholder_is_unknown():
    with pytest.raises(ValueError, match="Scenario 'x'"):
        catalog.fill("hi {nobody}", "Scenario 'x'", partner="Dev")


def test_fill_lists_the_placeholders_that_are_available():
    with pytest.raises(ValueError, match=r"\{partner\}"):
        catalog.fill("hi {nobody}", "somewhere", partner="Dev")


# ---------------------------------------------------------------------------
# The shipped catalogues
# ---------------------------------------------------------------------------

def test_the_shipped_personas_load():
    personas = load_personas()
    assert len(personas) >= 2
    assert all(p.bio and p.style for p in personas)


def test_the_shipped_scenarios_load_and_render_for_both_sides():
    scenarios = load_scenarios()
    assert len(scenarios) >= 2
    for s in scenarios:
        assert s.tagline, f"{s.name} has no tagline for the menu"
        for is_first in (True, False):
            text = s.setting_for("Lena", "Dev", is_first)
            assert text and "{" not in text
        assert "{" not in s.opener_for("Lena", "Dev")


def test_the_shipped_objectives_load_and_render():
    objectives = load_objectives()
    assert len(objectives) >= 2
    for o in objectives:
        assert o.tagline, f"{o.name} has no tagline for the menu"
        for text in (
            o.goal_for("Lena", "Dev"),
            o.reminder_for("Lena", "Dev"),
            o.notes_for("Lena", "Dev"),
        ):
            assert "{" not in text


def test_the_config_defaults_name_entries_that_exist():
    import config
    assert catalog.find(load_scenarios(), config.SCENARIO)
    assert catalog.find(load_objectives(), config.OBJECTIVE_A)
    assert catalog.find(load_objectives(), config.OBJECTIVE_B)


# ---------------------------------------------------------------------------
# Scenario / Objective behaviour
# ---------------------------------------------------------------------------

def test_scenario_shows_each_side_only_its_own_line():
    s = Scenario(name="s", setting="Shared.", opener="(go)",
                 first="You host.", second="You visit.")
    assert s.setting_for("Lena", "Dev", True) == "Shared. You host."
    assert s.setting_for("Lena", "Dev", False) == "Shared. You visit."


def test_scenario_without_sides_reads_the_same_to_both():
    s = Scenario(name="s", setting="Shared.", opener="(go)")
    assert s.setting_for("Lena", "Dev", True) == s.setting_for("Dev", "Lena", False)


def test_scenario_appends_the_knowledge_line_for_both():
    s = Scenario(name="s", setting="Shared.", opener="(go)",
                 knowledge="You know nothing about {partner}.")
    for is_first in (True, False):
        assert "You know nothing about Dev." in s.setting_for("Lena", "Dev", is_first)


def test_objective_notes_are_indented_to_sit_under_the_standard_headings():
    o = Objective(name="o", goal="g", notes="FIRST: one\nSECOND: two about {partner}")
    assert o.notes_for("Lena", "Dev") == (
        "  FIRST: one\n  SECOND: two about Dev"
    )


def test_objective_without_notes_or_reminder_returns_empty_strings():
    o = Objective(name="o", goal="g")
    assert o.notes_for("Lena", "Dev") == ""
    assert o.reminder_for("Lena", "Dev") == ""


def test_objective_owner_and_speaker_mean_the_same_person_in_notes():
    o = Objective(name="o", goal="g", notes="A: {owner}\nB: {speaker}")
    assert o.notes_for("Lena", "Dev") == "  A: Lena\n  B: Lena"
