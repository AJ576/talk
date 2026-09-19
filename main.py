#!/usr/bin/env python3
"""Two personas chat forever; a third model keeps the running memory condensed.

Setup:
    ollama pull llama3.2 && ollama pull mistral   (or change models in config.py)
Run:
    python main.py    (Ctrl+C to stop)

Output (both append-only, written to disk in real time, never overwritten):
    transcript.txt   every message
    memory.txt       every condensed-summary update; the last entry is the latest
"""

import sys

import config
from conversation import Conversation
from llm import LLMError, OllamaClient
from memory import ConversationMemory, Summarizer
from personas import OPENER, PERSONAS, SCENARIO
from storage import AppendLog


def main():
    client = OllamaClient(config.OLLAMA_URL)
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
            client, PERSONAS, memory, SCENARIO, OPENER, transcript_log, memory_log
        )
        try:
            conversation.run()
        except KeyboardInterrupt:
            print(f"\nStopped. Saved to {config.TRANSCRIPT_PATH} and {config.MEMORY_PATH}")
        except (LLMError, RuntimeError) as e:
            sys.exit(f"\nError: {e}\nEverything so far is saved in {config.TRANSCRIPT_PATH}.")


if __name__ == "__main__":
    main()
