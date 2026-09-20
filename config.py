"""All tunable settings live here. Edit values, nothing else needs to change."""

# --- Ollama ------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/chat"

# Context window sent with every request. Ollama's default is small and it
# silently cuts off the start of the prompt when it overflows, which would make
# the personas slowly forget who they are. 8192 fits the persona prompt, the
# summary and the verbatim window comfortably. Raise it if you raise the memory
# settings below (bigger = more RAM).
NUM_CTX = 8192

# --- Models (any models you've pulled with `ollama pull`) ----------------------
MODEL_A = "llama3.2"          # speaks as the first persona (the host)
MODEL_B = "llama3.2"          # speaks as the second persona (the guest)
SUMMARIZER_MODEL = "llama3.2" # third model: only condenses, never chats

# --- Personas ------------------------------------------------------------------
PERSONAS_PATH = "personas.md"  # relative paths are resolved next to the scripts

# --- How each speaker is shown the conversation ---------------------------------
# True  = "script mode": the recent messages go to the model as one script
#         ("Lena: ... Dev: ...") followed by "write Lena's next message". Nobody is
#         the "user", so the model has no one to please and tends to nod along less.
# False = classic chat mode: the partner's lines arrive as user messages and the
#         speaker's own lines as assistant messages.
SCRIPT_MODE = False

# --- Memory / condensing -------------------------------------------------------
# Each person keeps their OWN running summary of the conversation, written from
# their side (they remember more of what they said and what touched them).
# Both summaries are updated together, so a condense step costs two summarizer calls.
# True  = notes in first person ("I told Dev ...", "Dev said ...")
# False = notes in third person, but still from that person's side
MEMORY_FIRST_PERSON = True
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

# --- Repetition ----------------------------------------------------------------
# Master switch for the whole repetition remover (both layers below).
# True  = on, as described below.
# False = fully off: no token penalty (sent as 1.0), no phrase-overlap check, no
#         regenerating. Replies are used exactly as the model wrote them.
# (To turn off only layer 2, keep this True and set REPEAT_MAX_RETRIES = 0.)
REPEAT_REMOVER = False

# Two layers. (1) The model itself is discouraged from reusing recent tokens.
# Raise REPEAT_PENALTY for less repetition; above ~1.3 replies start to get odd.
REPEAT_PENALTY = 1.3
REPEAT_LAST_N = 256           # how many recent tokens the penalty looks back over
# (2) After each reply, the share of its 4-word phrases that already appeared in
# the last REPEAT_CHECK_TURNS messages is measured. Over REPEAT_MAX_OVERLAP, the
# reply is regenerated (with a nudge and a bit more randomness), up to
# REPEAT_MAX_RETRIES times, and the least repetitive attempt is kept.
# Set REPEAT_MAX_RETRIES = 0 to turn this off.
REPEAT_CHECK_TURNS = 6
REPEAT_MAX_OVERLAP = 0.25
REPEAT_MAX_RETRIES = 2

# --- Reliability ---------------------------------------------------------------
OLLAMA_TIMEOUT = 600          # seconds to wait for one reply before giving up on it
MAX_CONSECUTIVE_ERRORS = 5    # this many failed replies in a row stops the run
RETRY_WAIT_SECONDS = 10       # pause before retrying after a failed reply

# --- Run control ---------------------------------------------------------------
MAX_TURNS = None              # None = run forever (Ctrl+C to stop)
TURN_DELAY_SECONDS = 0.0      # pause between messages, if you want it slower
TRANSCRIPT_PATH = "transcript.txt"  # append-only: every message, fsynced as it happens
MEMORY_PATH = "memory.txt"          # append-only: both people's summary after every update, fsynced as it happens