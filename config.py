"""All tunable settings live here. Edit values, nothing else needs to change."""

# --- Ollama ------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/chat"

# --- Models (any models you've pulled with `ollama pull`) ----------------------
MODEL_A = "gemma4:12b"          # speaks as the first persona
MODEL_B = "gemma4:12b"           # speaks as the second persona
SUMMARIZER_MODEL = "llama3.2" # third model: only condenses, never chats

# --- Memory / condensing -------------------------------------------------------
# Recent turns are kept word-for-word. When there are MAX_RECENT_TURNS of them,
# the oldest CONDENSE_BATCH turns are folded into the running summary.
# So the verbatim window swings between (MAX - BATCH) and MAX turns.
MAX_RECENT_TURNS = 14
CONDENSE_BATCH = 8
SUMMARY_MAX_WORDS = 250       # the summary is rewritten each time and kept under this

# --- Generation ----------------------------------------------------------------
SPEAKER_TEMPERATURE = 0.9     # higher = more varied conversation
SUMMARIZER_TEMPERATURE = 0.2  # lower = more faithful notes
REPLY_MAX_TOKENS = 180        # cap on one message; a cut-off last sentence is dropped

# --- Reliability ---------------------------------------------------------------
OLLAMA_TIMEOUT = 600          # seconds to wait for one reply before giving up on it
MAX_CONSECUTIVE_ERRORS = 5    # this many failed replies in a row stops the run
RETRY_WAIT_SECONDS = 10       # pause before retrying after a failed reply

# --- Run control ---------------------------------------------------------------
MAX_TURNS = None              # None = run forever (Ctrl+C to stop)
TURN_DELAY_SECONDS = 0.0      # pause between messages, if you want it slower
TRANSCRIPT_PATH = "transcript.txt"  # append-only: every message, fsynced as it happens
MEMORY_PATH = "memory.txt"          # append-only: every summary update, fsynced as it happens