# Two personas, one long conversation

Two local LLMs (via [Ollama](https://ollama.com)) play two personas talking to
each other, forever. A third model condenses the conversation into memory as it
grows, so each persona can keep going far past what fits in one context window.

In the current setup the personas are chatting online, have never met, and each
one privately suspects the other might be an AI pretending to be human. Every
reply is expected to defend itself and then push the other person for a slip-up.
Nobody is ever allowed to admit they're the AI — that's the game.

```
Sam:    that sounds oddly specific for someone who was "just making coffee"
Nora:   I burned the coffee, actually, because I was on the phone with my sister.
        Ask her yourself. What were YOU doing thirty seconds before you opened this chat?
```

Everything runs locally. Nothing is sent anywhere except your own Ollama server.

## Contents

- [Quick start](#quick-start)
- [How a conversation runs](#how-a-conversation-runs)
- [The suspicion game](#the-suspicion-game)
- [Personas](#personas)
- [Memory: recent turns + per-person notes](#memory-recent-turns--per-person-notes)
- [Script mode vs. chat mode](#script-mode-vs-chat-mode)
- [Repetition control](#repetition-control)
- [Output files](#output-files)
- [Configuration reference](#configuration-reference)
- [File-by-file overview](#file-by-file-overview)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

## Quick start

1. Install [Ollama](https://ollama.com) and pull a model:
   ```bash
   ollama pull llama3.2
   ```
2. Make sure Ollama is running (it usually starts automatically; otherwise
   `ollama serve`).
3. Run:
   ```bash
   python main.py                # pick two personas from a menu
   python main.py Nora Caleb      # skip the menu; Nora hosts
   python main.py --list          # see who's available, then exit
   ```
4. Watch it in the terminal, or read along in `transcript.txt`. `Ctrl+C` stops
   it cleanly at any point; nothing already written is lost.

No API keys, no internet access needed beyond talking to your own Ollama
instance at `http://localhost:11434`.

## How a conversation runs

`main.py` loads the personas, builds the two models' clients, and hands
everything to `Conversation.run()` in `conversation.py`. The loop, forever
(or until `MAX_TURNS`):

1. Figure out whose turn it is (they alternate; the host goes first).
2. Build that persona's system prompt: their bio, style, the scene, **their
   own** memory of the conversation so far, the conversation rules, and the
   suspicion-game instructions.
3. Build the message history — either classic chat turns or one "script" of
   the recent conversation, depending on `SCRIPT_MODE` (see below).
4. Send it to that persona's model (`MODEL_A` or `MODEL_B` in `config.py`),
   streaming tokens to the console as they arrive.
5. Clean the reply (strip name prefixes, stage directions, filler agreement
   openers, an accidentally-quoted whole message, a cut-off trailing sentence).
6. Optionally regenerate if it repeats recent wording too closely (see
   [Repetition control](#repetition-control)).
7. Write the finished message to `transcript.txt` (flushed and fsynced
   immediately) and add it to memory.
8. If memory just hit its limit, condense the oldest batch of turns into each
   person's running notes, and log both updated notes to `memory.txt`.

A separate model, `SUMMARIZER_MODEL`, does the condensing. It never sees or
continues the live conversation — it's only ever handed "old notes + a chunk
of transcript" and asked to rewrite the notes.

## The suspicion game

This isn't a neutral chat anymore — it's an adversarial framing layered on top.
Both personas are told (in `MISSION` in `prompts.py`):

- They strongly suspect their partner is an AI posing as a human, and their
  partner suspects the same about them.
- They are certain **they themselves** are human, so an accusation is
  insulting, not something to entertain.
- They win only if the partner admits, in plain words, to being an AI. They
  lose if they admit it themselves, or if they leave/say goodbye.
- Every message is expected to (1) defend themselves with something concrete
  and specific if they were just challenged, and (2) end with one *new* probe
  or challenge aimed at the partner — a question, a demand, a pointed
  observation about something the partner said.

A private, per-request reminder (`MISSION_REMINDER`) is appended to the last
message of each API call to reinforce this, but it is **never** written to
the transcript or memory — the personas' own record of the conversation only
contains what was actually said out loud.

The personas are also explicitly told they know nothing about their partner's
life except what's been said in the chat, and must never hand their partner
their own job, history, or backstory — that's what keeps each side's "defense"
material distinct and checkable.

If you want the calmer, non-adversarial version back (two friends catching up,
no suspicion game), see [Reverting to a relaxed conversation](#reverting-to-a-relaxed-conversation)
below.

### The scenario

`personas.py` sets the scene: the two have never met, they only know each
other from typing back and forth, so questions like "what's around you right
now" or "describe your room" are natural probes, not non-sequiturs. The host
is given an opener that starts casually, without giving away the suspicion
yet.

## Personas

Personas live in `personas.md`, parsed by `personas.py`. Each is a `##`
heading (the name used everywhere — transcript, memory, prompts) with two
required subsections and one optional one:

```markdown
## Name

### Tagline
One line, shown in the picker menu.

### Bio
Who they are. Concrete, specific, a few sentences.

### Style
How they talk: rhythm, habits, verbal tics, what they lean on.
```

Unknown sections are ignored, so you can add scratch notes if you want. At
least two personas are required; there's no upper limit. Fifteen are
currently defined:

| Name | Who |
|---|---|
| Priya | computational neuroscientist |
| Theo | philosophy professor |
| Idris | field ecologist |
| Nadia | chef, owns two restaurants |
| Gus | retired union electrician |
| Ruth | retired judge |
| Sam | barista / part-time student, mid-20s |
| Aisha | ER nurse on night shifts, late-20s |
| Marcus | middle-school teacher/coach, early-30s |
| Chloe | accountant, early-30s |
| Tom | warehouse manager, dad of two, mid-30s |
| Hannah | elementary school librarian, late-30s |
| Jordan | junior designer, new to the city, mid-20s |
| Dev | startup founder, late-20s |
| Lena | sailing instructor, late-30s |
| **Nora** | insurance adjuster with a nagging feeling she isn't real |
| **Caleb** | pharmacy tech with the same feeling, never voiced |

**Nora and Caleb** are a special pair: their bios give them a genuine,
unresolved suspicion about their own reality, on top of the suspicion game
both sides always play. Neither is told to ever *conclude* they're an AI —
the doubt is meant to stay a doubt, not become a scripted confession — but
because they're also playing the mission game against each other, and because
each one's own uncertainty is exactly the kind of thing the other's probes
might dig into, they're the pairing most likely to spiral in an interesting
way. Worth pairing them together at least once.

Pick any two names with `python main.py Name1 Name2`, or omit names to get
an interactive numbered menu (`--list` just prints it and exits).

## Memory: recent turns + per-person notes

There is **one** shared buffer of recent turns (`ConversationMemory.recent`)
— both people heard the same messages, so there's nothing to duplicate there.
What's private is the **summary**: each persona has their own running notes on
the older conversation, written from their own side.

- `MAX_RECENT_TURNS` (default 14): how many recent messages are kept
  word-for-word.
- `CONDENSE_BATCH` (default 8): once the buffer is full, the *oldest* 8 of
  those turns are folded into memory and dropped from the verbatim buffer.
  So the verbatim window swings between `MAX_RECENT_TURNS - CONDENSE_BATCH`
  and `MAX_RECENT_TURNS` turns.
- Condensing costs **two** summarizer calls (one per person) on the exact
  same batch of old turns, each producing that person's own updated notes.
  Nothing is committed unless both calls succeed — if one fails, neither
  summary changes, and the buffer is retried after `RETRY_AFTER_TURNS` turns
  (a call that already succeeded isn't wasted; it's kept pending until its
  partner also succeeds).
- If the summarizer keeps failing long enough that the buffer grows past
  `2 * MAX_RECENT_TURNS`, the oldest batch is dropped unsummarized rather than
  letting the prompt grow forever.

### What the notes contain

The summarizer prompt organizes each person's notes under four fixed
headings (skipping any that would be empty):

- **What `{owner}` told `{partner}` about themselves** — so the owner stays
  consistent with their own story.
- **What `{partner}` told `{owner}`** — the partner's checkable claims.
- **Contradictions and dodges** — where the partner's story didn't line up,
  or they avoided a direct question.
- **Probes `{owner}` has already used** — so the same challenge isn't
  repeated turn after turn.

It's told to record only what was actually said, never invented feelings or
motives, and to never write a "both agree" section (this is a leftover
instruction from the game's more sociable predecessor, but it still helps
keep the notes factual rather than editorializing).

`MEMORY_FIRST_PERSON` (default `True`) controls the voice:

- `True`: notes are written as the owner's own first-person notes ("I told
  Caleb about my walk; Caleb said his grandmother lives nearby").
- `False`: third person, but still organized from the owner's side.

If notes ever come back over `SUMMARY_MAX_WORDS`, they're recursively
re-summarized (up to `MAX_SHRINK_PASSES` times, each pass targeting 80% of
the limit) before being handed to the speaker; if compression stalls, they're
trimmed line-by-line as a last resort.

**What separate memories do and don't fix:** each person's notes now
emphasize their own side and their own probes, which helps them stay
consistent and stops them from silently inheriting the other's phrasing as
their own. It does **not** give them any private information the other
doesn't also have access to (both heard the same transcript) — it's a
difference in emphasis, not in knowledge. Long-run drift (two characters
quietly turning into family, or a running bit escalating past where it makes
sense) is still possible, since a rewritten summary can lose or blur older
detail; nothing here pins facts down the way something in the fixed system
prompt (bio, scenario) does.

## Script mode vs. chat mode

`SCRIPT_MODE` in `config.py` controls how the recent conversation is handed
to the speaking model:

- **`False` (chat mode)** — the classic shape. The partner's lines arrive as
  `user` messages, the speaker's own past lines as `assistant` messages.
- **`True` (script mode)** — the whole recent conversation is sent as a
  single `user` message: a plain script (`"Nora: ...\n\nCaleb: ..."`) followed
  by `"Write Nora's next message. Output only what Nora says..."`. Nobody is
  cast as "the user" the model is trying to please, which tends to cut down
  on reflexive agreement/flattery in small models. A `stop` sequence
  (`"\n{partner.name}:"`) keeps the model from continuing on and writing the
  other side; `clean_reply` also cuts anything that slips through after a
  `"Partner:"` line.

Both modes use the same per-person memory and the same system prompt. Only
the message history shape changes. It's read once at startup — flip it in
`config.py` and restart to switch.

## Repetition control

Two independent layers, both governed by the master switch `REPEAT_REMOVER`:

1. **Sampling-level penalty.** When enabled, `REPEAT_PENALTY` /
   `REPEAT_LAST_N` are passed straight to Ollama, discouraging the model from
   reusing recent tokens. When `REPEAT_REMOVER` is `False`, this is sent as
   `1.0` (no penalty at all), not omitted.
2. **Post-hoc overlap check.** After a reply is generated, `repetition_score`
   measures what share of its 4-word phrases already appeared in the last
   `REPEAT_CHECK_TURNS` messages (either speaker). If that's above
   `REPEAT_MAX_OVERLAP`, the reply is regenerated — with `REPEAT_NUDGE`
   appended to the system prompt and the temperature nudged up — up to
   `REPEAT_MAX_RETRIES` times, keeping the least-repetitive attempt seen.

Set `REPEAT_REMOVER = False` to turn off both layers entirely and use
whatever the model produces as-is. To keep layer 1 but drop layer 2, leave
`REPEAT_REMOVER = True` and set `REPEAT_MAX_RETRIES = 0`.

`clean_reply` also unconditionally strips things that aren't really
"repetition" but are still unwanted habits: a leading `"Name:"` label,
`*stage directions*` (including a lone unclosed `*action` if the reply got
cut off mid-action), filler agreement openers ("Exactly,", "Absolutely,"),
a stock "I love how you..." compliment, and a whole reply wrapped in quotes.

## Output files

Both files are **append-only** — opened in append mode, flushed and
`fsync`'d after every write, never truncated or rewritten, including across
separate runs. A crash can lose at most the message currently mid-generation.

- **`transcript.txt`** — every message, in order:
  ```
  === New session | 2026-09-20T15:53:23 | Aisha (host) & Jordan ===

  Aisha: <message>

  Jordan: <message>
  ...
  ```
- **`memory.txt`** — both people's condensed notes, logged every time memory
  is updated:
  ```
  --- Aisha's memory after message 14 | 2026-09-20T15:55:58 ---
  <Aisha's current notes>

  --- Jordan's memory after message 14 | 2026-09-20T15:55:58 ---
  <Jordan's current notes>
  ```
  The last entry for each name is that person's latest, current memory —
  useful for watching how it evolves (or drifts) over a long run.

Both paths are configurable (`TRANSCRIPT_PATH`, `MEMORY_PATH`) and resolved
relative to wherever you run the script from.

## Configuration reference

Everything tunable lives in `config.py`, grouped and commented there. Summary:

| Setting | Default | What it does |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Where Ollama's chat API is |
| `NUM_CTX` | `8192` | Context window sent with every request. Too small and Ollama silently truncates the *start* of the prompt (the persona/rules), not the end — raise this if you raise the memory settings below |
| `MODEL_A` / `MODEL_B` | `llama3.2` | Models for the host / guest persona |
| `SUMMARIZER_MODEL` | `llama3.2` | Model used only for condensing memory |
| `PERSONAS_PATH` | `personas.md` | Resolved relative to the scripts if not absolute |
| `SCRIPT_MODE` | `False` | See [Script mode vs. chat mode](#script-mode-vs-chat-mode) |
| `MEMORY_FIRST_PERSON` | `True` | First- vs. third-person notes |
| `MAX_RECENT_TURNS` | `14` | Verbatim buffer size before condensing |
| `CONDENSE_BATCH` | `8` | How many oldest turns get folded in per condense (must be `<` `MAX_RECENT_TURNS`) |
| `SUMMARY_MAX_WORDS` | `350` | Cap on each person's notes |
| `SPEAKER_TEMPERATURE` | `0.9` | Higher = more varied replies |
| `SUMMARIZER_TEMPERATURE` | `0.2` | Lower = more faithful notes |
| `REPLY_MAX_TOKENS` | `180` | Per-message cap; a cut-off last sentence is dropped |
| `REPEAT_REMOVER` | `False` | Master switch for both repetition layers |
| `REPEAT_PENALTY` / `REPEAT_LAST_N` | `1.3` / `256` | Ollama sampling penalty, when enabled |
| `REPEAT_CHECK_TURNS` | `6` | Window checked for phrase overlap |
| `REPEAT_MAX_OVERLAP` | `0.25` | Overlap share that triggers a regeneration |
| `REPEAT_MAX_RETRIES` | `2` | Regeneration attempts before giving up and keeping the best one |
| `OLLAMA_TIMEOUT` | `600` (sec) | Per-reply timeout |
| `MAX_CONSECUTIVE_ERRORS` | `5` | Stop the run after this many failed replies in a row |
| `RETRY_WAIT_SECONDS` | `10` | Pause before retrying a failed reply |
| `MAX_TURNS` | `None` | `None` = run forever (`Ctrl+C` to stop) |
| `TURN_DELAY_SECONDS` | `0.0` | Pause between messages, if you want it slower to read |
| `TRANSCRIPT_PATH` / `MEMORY_PATH` | `transcript.txt` / `memory.txt` | Output file locations |

## File-by-file overview

| File | Responsibility |
|---|---|
| `main.py` | CLI entry point: argument parsing, persona picker menu, wires everything together |
| `config.py` | All tunables, described above |
| `personas.py` | Parses `personas.md`, builds the scenario text |
| `personas.md` | The persona data itself — edit this to add/change people |
| `prompts.py` | Every prompt string: flow rules, the suspicion-game mission, summarizer/shrink prompts, script-mode framing |
| `conversation.py` | The main loop; reply cleaning (`clean_reply`, `strip_actions`); repetition scoring and retry logic |
| `memory.py` | `Turn`, `Summarizer` (condenses/shrinks notes via the LLM), `ConversationMemory` (verbatim buffer + per-person summaries) |
| `llm.py` | Thin Ollama client (`OllamaClient`) and `LLMError` — swap this file to use a different backend |
| `storage.py` | `AppendLog`, the crash-safe append-only file writer |

## Troubleshooting

- **"Model 'x' gave no response for 600s"** — Ollama is likely running on CPU
  or is out of RAM. Try a smaller model or raise `OLLAMA_TIMEOUT`.
- **Ollama returned 404** — the model isn't pulled yet; the error message
  includes the exact `ollama pull ...` command to run.
- **Replies feel cut off** — `REPLY_MAX_TOKENS` is the hard cap per message;
  a dangling half-sentence at the end is dropped automatically
  (`_drop_cut_off_tail`), which can make replies feel short. Raise the cap if
  you want longer messages.
- **Personas seem to be forgetting who they are over a long run** — check
  Ollama's own logs for a context-truncation warning. If `NUM_CTX` is too
  small for your `MAX_RECENT_TURNS` / `SUMMARY_MAX_WORDS`, Ollama silently
  drops the *start* of the prompt (where the bio and rules live) rather than
  erroring. Raise `NUM_CTX`, or lower the memory settings.
- **A summarizer call keeps failing** — the run doesn't stop; it waits
  `RETRY_AFTER_TURNS` turns and tries again. If it fails long enough that the
  verbatim buffer grows past `2 * MAX_RECENT_TURNS`, the oldest batch is
  dropped unsummarized so the prompt doesn't grow forever. You'll see this
  logged to the console either way.
- **A model writes the other person's lines too** — this mostly matters in
  script mode; check that the `stop` sequence is actually reaching Ollama
  (`"\n{partner.name}:"`) and that `clean_reply` is receiving `partner=...`.

## Known limitations

- **No real information asymmetry.** Both personas hear the exact same
  transcript; per-person memory changes *emphasis*, not *knowledge*. Don't
  expect one side to "know something the other doesn't" beyond what's been
  said out loud.
- **Long-run drift.** Because the running notes are rewritten (not appended)
  on every condense, a detail introduced early and never repeated can fade
  out of a person's memory over a very long conversation, while something
  vivid and recent dominates. Nothing pins a fact down except the fixed
  system prompt (bio, style, scenario) — anything that needs to be permanent
  should live there, not rely on surviving the summarizer indefinitely.
- **Small local models will sometimes ignore instructions** — the mission
  format (defend, then probe), the "never admit you're an AI" rule, and the
  notes format are all things a 3B-class model will occasionally drop or
  garble. `clean_reply` and the retry/shrink logic catch some of this, not
  all of it.
- **No test suite.** This has been exercised against a scripted fake model
  during development, not against a live Ollama server for this exact
  revision — read a bit of `transcript.txt` and `memory.txt` after starting a
  fresh run before leaving it going unattended for a long time.

### Reverting to a relaxed conversation

If you'd rather go back to two people just catching up, with no suspicion
game: replace `MISSION` in `prompts.py` with an empty string (and drop the
`build_speaker_prompt` call that appends it), remove the "you know nothing
about {partner}'s life" line if you want them to be old friends instead of
strangers, and change `SCENARIO` / `OPENER` in `personas.py` back to a
shared, in-person setting. The memory and script-mode machinery underneath
doesn't depend on the mission at all.
