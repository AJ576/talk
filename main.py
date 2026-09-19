#!/usr/bin/env python3
"""Two personas chat forever; a third model keeps the running memory condensed.

Setup:
    ollama pull llama3.2      (or change the models in config.py)
Run:
    python main.py                  pick the two personas from a menu
    python main.py Priya Theo       skip the menu (the first name hosts, at their place)
    python main.py --list           show who's available
    Ctrl+C to stop.

Personas live in personas.md. Add or edit people there.

Output (both append-only, written to disk in real time, never overwritten):
    transcript.txt   every message
    memory.txt       every condensed-summary update; the last entry is the latest
"""

import argparse
import sys

import config
from conversation import Conversation
from llm import LLMError, OllamaClient
from memory import ConversationMemory, Summarizer
from personas import OPENER, build_scenario, find_persona, load_personas
from storage import AppendLog


def parse_args():
    parser = argparse.ArgumentParser(description="Run a conversation between two personas.")
    parser.add_argument(
        "names", nargs="*", metavar="PERSONA",
        help="two persona names; the first is the host (the scene is at their place)",
    )
    parser.add_argument("--list", action="store_true", help="list personas and exit")
    return parser.parse_args()


def print_menu(personas):
    for i, p in enumerate(personas, 1):
        print(f"  {i}. {p.name:<10} {p.tagline}")


def ask(prompt, personas, exclude=None):
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(personas):
            match = personas[int(raw) - 1]
        else:
            match = find_persona(personas, raw) if raw else None
        if match is None:
            print("  Not in the list, try again.")
        elif exclude and match.name == exclude.name:
            print("  Pick someone different.")
        else:
            return match


def choose_personas(personas, names):
    if len(names) == 2:
        chosen = [find_persona(personas, n) for n in names]
        for n, p in zip(names, chosen):
            if p is None:
                sys.exit(f"No persona called '{n}'. Available: "
                         + ", ".join(p.name for p in personas))
        if chosen[0].name == chosen[1].name:
            sys.exit("Pick two different personas.")
        return chosen
    if names:
        sys.exit("Give exactly two persona names, or none to use the menu.")

    print("Personas:\n")
    print_menu(personas)
    print()
    host = ask("Host (the evening is at their place), number or name: ", personas)
    guest = ask("Guest, number or name: ", personas, exclude=host)
    return [host, guest]


def main():
    # A console that can't print some character shouldn't crash the run.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    args = parse_args()
    try:
        personas = load_personas()
    except ValueError as e:
        sys.exit(str(e))

    if args.list:
        print_menu(personas)
        return

    try:
        pair = choose_personas(personas, args.names)
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")
    host, guest = pair
    print(f"\n{host.name} is hosting {guest.name}. Ctrl+C to stop.\n")

    client = OllamaClient(config.OLLAMA_URL, config.OLLAMA_TIMEOUT, config.NUM_CTX)
    summarizer = Summarizer(
        client,
        config.SUMMARIZER_MODEL,
        config.SUMMARY_MAX_WORDS,
        config.SUMMARIZER_TEMPERATURE,
    )
    memory = ConversationMemory(summarizer, config.MAX_RECENT_TURNS, config.CONDENSE_BATCH)

    with AppendLog(config.TRANSCRIPT_PATH) as transcript_log, AppendLog(
        config.MEMORY_PATH
    ) as memory_log:
        conversation = Conversation(
            client,
            [config.MODEL_A, config.MODEL_B],
            pair,
            memory,
            lambda speaker, partner: build_scenario(speaker, partner, host),
            OPENER,
            transcript_log,
            memory_log,
        )
        try:
            conversation.run()
        except KeyboardInterrupt:
            print(f"\nStopped. Saved to {config.TRANSCRIPT_PATH} and {config.MEMORY_PATH}")
        except (LLMError, RuntimeError) as e:
            sys.exit(f"\nError: {e}\nEverything so far is saved in {config.TRANSCRIPT_PATH}.")


if __name__ == "__main__":
    main()