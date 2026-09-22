#!/usr/bin/env python3
"""Two personas talk forever; a third model keeps each one's own memory condensed.

Who they are, where they are, and what they want are three separate catalogues,
so any combination works:

    personas.md     who is talking       (17 people)
    scenarios.md    the setting          (online, hosting, first-meeting, ...)
    objectives.md   what each one wants  (unmask, interview, guarded, ...)

Setup:
    ollama pull llama3.2      (or change the models in config.py)
Run:
    python main.py                  pick everything from a menu
    python main.py Priya Theo       skip the persona menu (the first name opens)
    python main.py --list           show personas, scenarios and objectives
    Ctrl+C to stop.

    python main.py Nora Caleb --scenario hosting --objectives recruit guarded

The two objectives are per speaker and don't have to match: the example above is
one person working up to an ask while the other protects a secret.

Output (append-only, written to disk in real time, never overwritten):
    transcript.txt   every message
    memory.txt       both people's condensed notes after every update; the last
                     entry for each person is their latest
    run_stats.json   overwritten each turn: turns, retries, failures so far
"""

import argparse
import sys

import config
from conversation import Conversation
from llm import LLMError, OllamaClient
from memory import ConversationMemory, Summarizer
from objectives import load_objectives
from personas import find_persona, load_personas
from scenarios import load_scenarios
from stats import RunStats, StatsLog
from storage import AppendLog

import catalog


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a conversation between two personas.",
    )
    parser.add_argument(
        "names", nargs="*", metavar="PERSONA",
        help="two persona names; the first one opens the conversation",
    )
    parser.add_argument(
        "--scenario", metavar="NAME",
        help=f"the setting (default: {config.SCENARIO})",
    )
    parser.add_argument(
        "--objectives", nargs="+", metavar="NAME",
        help="what each speaker wants, in persona order. One name gives both "
             f"the same objective (default: {config.OBJECTIVE_A} "
             f"{config.OBJECTIVE_B})",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="list personas, scenarios and objectives, then exit",
    )
    return parser.parse_args()


def print_menu(items):
    for i, item in enumerate(items, 1):
        print(f"  {i:>2}. {item.name:<16} {item.tagline}")


def print_catalogues(personas, scenarios, objectives):
    for title, items in (
        ("Personas", personas), ("Scenarios", scenarios), ("Objectives", objectives)
    ):
        print(f"{title}:")
        print_menu(items)
        print()


def ask(prompt, items, exclude=None, default=None):
    """Number or name, case-insensitive. With a `default`, an empty line takes it."""
    if default is not None:
        prompt = f"{prompt} [{default.name}]: "
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            match = items[int(raw) - 1]
        else:
            match = catalog.find(items, raw) if raw else None
        if match is None:
            print("  Not in the list, try again.")
        elif exclude and match.name == exclude.name:
            print("  Pick someone different.")
        else:
            return match


def require(items, name, kind):
    """Look `name` up or exit with the list of what's available."""
    match = catalog.find(items, name)
    if match is None:
        sys.exit(
            f"No {kind} called '{name}'. Available: "
            + ", ".join(i.name for i in items)
        )
    return match


def choose_personas(personas, names):
    if len(names) == 2:
        chosen = [require(personas, n, "persona") for n in names]
        if chosen[0].name == chosen[1].name:
            sys.exit("Pick two different personas.")
        return chosen
    if names:
        sys.exit("Give exactly two persona names, or none to use the menu.")

    print("Personas:\n")
    print_menu(personas)
    print()
    first = ask("Who opens the chat, number or name", personas)
    second = ask("Who they're chatting with, number or name", personas, exclude=first)
    return [first, second]


def resolve_scenario(scenarios, requested):
    """Validate a `--scenario` value. None means "ask for it later"."""
    return require(scenarios, requested, "scenario") if requested else None


def resolve_objectives(objectives, requested):
    """Validate `--objectives`: one name for both, or one per speaker. None
    means "ask for them later"."""
    if not requested:
        return None
    if len(requested) > 2:
        sys.exit(
            "Give one or two objectives (one means both speakers get the same). "
            "Got: " + " ".join(requested)
        )
    names = requested if len(requested) == 2 else requested * 2
    return [require(objectives, n, "objective") for n in names]


def pick_scenario(scenarios):
    print("\nScenarios:\n")
    print_menu(scenarios)
    print()
    return ask("Setting, number or name", scenarios,
               default=require(scenarios, config.SCENARIO, "scenario"))


def pick_objectives(objectives, pair):
    """One objective per speaker, asked for separately: they don't have to match."""
    print("\nObjectives:\n")
    print_menu(objectives)
    print()
    defaults = [
        require(objectives, config.OBJECTIVE_A, "objective"),
        require(objectives, config.OBJECTIVE_B, "objective"),
    ]
    return [
        ask(f"What {p.name} wants, number or name", objectives, default=d)
        for p, d in zip(pair, defaults)
    ]


def main():
    # A console that can't print some character shouldn't crash the run.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    args = parse_args()
    try:
        personas = load_personas()
        scenarios = load_scenarios()
        objectives = load_objectives()
    except ValueError as e:
        sys.exit(str(e))

    if args.list:
        print_catalogues(personas, scenarios, objectives)
        return

    # Everything given on the command line is checked before anything is asked
    # for, so a typo surfaces immediately instead of halfway through the menu.
    scenario = resolve_scenario(scenarios, args.scenario)
    goals = resolve_objectives(objectives, args.objectives)
    try:
        pair = choose_personas(personas, args.names)
        if scenario is None:
            scenario = pick_scenario(scenarios)
        if goals is None:
            goals = pick_objectives(objectives, pair)
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")

    first, second = pair
    print(f"\n{scenario.name}: {first.name} ({goals[0].name}) "
          f"and {second.name} ({goals[1].name}). {first.name} opens. "
          "Ctrl+C to stop.\n")

    client = OllamaClient(config.OLLAMA_URL, config.OLLAMA_TIMEOUT, config.NUM_CTX)
    summarizer = Summarizer(
        client,
        config.SUMMARIZER_MODEL,
        config.SUMMARY_MAX_WORDS,
        config.SUMMARIZER_TEMPERATURE,
        config.MEMORY_FIRST_PERSON,
    )
    stats_log = StatsLog(config.STATS_PATH, RunStats(
        speaker_a=first.name, speaker_b=second.name,
        model_a=config.MODEL_A, model_b=config.MODEL_B,
        summarizer_model=config.SUMMARIZER_MODEL, script_mode=config.SCRIPT_MODE,
        scenario=scenario.name,
        objective_a=goals[0].name, objective_b=goals[1].name,
    ))
    # Each person's notes are shaped by their own objective, so one can be
    # tracking probes they've used while the other tracks what they've revealed.
    memory = ConversationMemory(
        summarizer, config.MAX_RECENT_TURNS, config.CONDENSE_BATCH,
        [p.name for p in pair],
        note_headings={
            p.name: g.notes_for(p.name, other.name)
            for p, g, other in zip(pair, goals, reversed(pair))
        },
        stats=stats_log.stats,
    )

    with AppendLog(config.TRANSCRIPT_PATH) as transcript_log, AppendLog(
        config.MEMORY_PATH
    ) as memory_log:
        conversation = Conversation(
            client,
            [config.MODEL_A, config.MODEL_B],
            pair,
            goals,
            memory,
            scenario,
            transcript_log,
            memory_log,
            stats_log,
        )
        try:
            conversation.run()
        except KeyboardInterrupt:
            print(f"\nStopped. Saved to {config.TRANSCRIPT_PATH} and {config.MEMORY_PATH}")
            stats_log.write()
        except (LLMError, RuntimeError) as e:
            stats_log.stats.fatal_error = str(e)
            stats_log.write()
            sys.exit(f"\nError: {e}\nEverything so far is saved in {config.TRANSCRIPT_PATH}.")


if __name__ == "__main__":
    main()
