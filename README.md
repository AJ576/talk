# Two personas, one long conversation

Two local LLMs (via [Ollama](https://ollama.com)) play two personas talking to
each other, forever. A third model condenses the conversation into memory as it
grows, so each persona can keep going far past what fits in one context window.

Three things are picked separately, from three markdown catalogues, and any
combination works:

| | file | what it is |
|---|---|---|
| **Who** | `personas.md` | the two people: bio and speaking style |
| **Where** | `scenarios.md` | the setting: chatting online, hosting someone, stuck at an airport gate |
| **What they want** | `objectives.md` | one goal *per speaker* — they don't have to match |

The default is the suspicion game: both people privately think the other is an
AI and try to force a confession. But the same two personas can be sat in a
kitchen with one of them working up to an ask and the other protecting a
secret, and it's a different conversation entirely.

```
$ python main.py Sam Nora --scenario online --objectives unmask unmask

Sam:    that sounds oddly specific for someone who was "just making coffee"
Nora:   I burned the coffee, actually, because I was on the phone with my sister.
        Ask her yourself. What were YOU doing thirty seconds before you opened this chat?
```

```
$ python main.py Lena Dev --scenario delayed-flight --objectives interview guarded

Lena:   Three cancellations? That's... quite a coincidence, I'd say. Did he happen
        to know what was going on with the flights after they cancelled?
Dev:    No, he just got the usual vague "technical issues" thing, which is never a
        good sign, right? I mean, it's always something.
```

Everything runs locally. Nothing is sent anywhere except your own Ollama server.

## Contents

- [Quick start](#quick-start)
- [How a conversation runs](#how-a-conversation-runs)
- [Personas](#personas)
- [Scenarios](#scenarios)
- [Objectives](#objectives)
- [The suspicion game](#the-suspicion-game)
- [Adding your own](#adding-your-own)
- [Memory: recent turns + per-person notes](#memory-recent-turns--per-person-notes)
- [Script mode vs. chat mode](#script-mode-vs-chat-mode)
- [Repetition control](#repetition-control)
- [Output files](#output-files)
- [Configuration reference](#configuration-reference)
- [File-by-file overview](#file-by-file-overview)
- [Troubleshooting](#troubleshooting)
- [Running the tests](#running-the-tests)
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
   python main.py                 # pick everything from a menu
   python main.py Nora Caleb      # skip the persona menu; Nora opens
   python main.py --list          # personas, scenarios and objectives, then exit

   # set the whole thing from the command line
   python main.py Nora Caleb --scenario hosting --objectives recruit guarded
   python main.py Lena Dev --scenario old-friends --objectives catch-up
   ```

   `--scenario` and `--objectives` default to `SCENARIO`, `OBJECTIVE_A` and
   `OBJECTIVE_B` in `config.py`. One name after `--objectives` gives both
   speakers the same goal; two gives them one each, in persona order.
4. Watch it in the terminal, or read along in `transcript.txt`. `Ctrl+C` stops
   it cleanly at any point; nothing already written is lost.

No API keys, no internet access needed beyond talking to your own Ollama
instance at `http://localhost:11434`.

## How a conversation runs

`main.py` loads the three catalogues, resolves the persona pair, the scenario
and the two objectives, and hands everything to `Conversation.run()` in
`conversation.py`. The loop, forever (or until `MAX_TURNS`):

1. Figure out whose turn it is (they alternate; `personas[0]` opens).
2. Build that persona's system prompt: their bio, style, **their side** of the
   scenario, **their own** memory of the conversation so far, the conversation
   rules, and last of all **their own** objective.
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

Nothing in the loop knows about any particular scenario or objective. Both are
plain data, resolved once at startup and then only ever asked for text:
`scenario.setting_for(...)`, `objective.goal_for(...)`, `objective.reminder_for(...)`.
Adding a new one means editing a markdown file, not touching Python.

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

## Scenarios

A scenario is the *setting only* — where the two people are and how they came
to be talking. It never says what either of them wants. Scenarios live in
`scenarios.md`, parsed by `scenarios.py`:

```markdown
## hosting

### Tagline
One of them is hosting the other at home for the evening

### Setting
It's a weekday evening. There's food, something to drink, and no
particular reason to hurry.

### First
You're at home, and {partner} has come over for the evening.

### Second
You're at {partner}'s place for the evening. You brought something with you.

### Opener
(You've just let {partner} in and poured them something.)
```

| Section | Required | Who sees it |
|---|---|---|
| `Tagline` | no | nobody — the menu and `--list` |
| `Setting` | **yes** | both people |
| `First` | no | only the first speaker |
| `Second` | no | only the second speaker |
| `Knowledge` | no | both — what they may assume they already know |
| `Opener` | **yes** | only the first speaker, only on turn 1 |

`{partner}` is the other person's name, `{speaker}` their own.

`First` and `Second` are what make asymmetric settings work: in `hosting` one
person is in their own kitchen and the other is a guest, and each is told only
their own side. Leave both out and the scenario reads identically to both.

`Knowledge` is the one that matters most in practice. Without it two personas
will cheerfully invent a shared history; `online` and `first-meeting` use it to
say they're strangers, and `old-friends` uses it to say the opposite.

Shipped: `online`, `hosting`, `first-meeting`, `delayed-flight`, `old-friends`,
`late-shift`.

## Objectives

An objective is what one person is trying to get out of the conversation.
**Each speaker gets their own**, so they don't have to match — that's the whole
point of the catalogue. Objectives live in `objectives.md`, parsed by
`objectives.py`:

```markdown
## interview

### Tagline
Learn everything about them, reveal little about yourself

### Goal
You want to come out of this knowing far more about {partner} than they
know about you.
...

### Reminder
Answer briefly, then ask {partner} one specific follow-up.

### Notes
QUESTIONS {owner} HAS ALREADY ASKED: so they aren't asked twice.
WHAT {owner} STILL WANTS TO KNOW: gaps, and details {partner} skipped past.
```

| Section | Required | Where it goes |
|---|---|---|
| `Tagline` | no | nobody — the menu and `--list` |
| `Goal` | **yes** | last in the system prompt, where it pulls hardest |
| `Reminder` | no | the last user message of *every* request |
| `Notes` | no | extra headings in this person's memory, one per line |

Paragraphs and numbered lists in `Goal` are kept exactly as written. A
`Reminder` is collapsed to one line.

The three parts do different jobs:

- **`Goal`** sets the behaviour. Write it in the second person, give it a shape
  to follow, and say what counts as winning *and* losing. Vague objectives
  produce vague conversations.
- **`Reminder`** keeps it there. A small model drifts away from a long system
  prompt after a few turns, and a one-line nudge attached to the newest message
  pulls it back. It is never written to `transcript.txt` and never folded into
  memory, so the other speaker never learns what this one is up to.
- **`Notes`** shapes what this person *remembers*. Memory is already per-person
  (see below), so the headings can be too: someone running `interview` keeps a
  list of questions they've already asked, while someone running `guarded`
  keeps track of how close the other one has come.

Shipped: `unmask`, `catch-up`, `interview`, `guarded`, `persuade`, `recruit`,
`confess`.

### Pairing them

The interesting runs are the mismatched ones:

| Pairing | What it produces |
|---|---|
| `unmask unmask` | the suspicion game — two people trying to out each other |
| `interview guarded` | one digs, one deflects; nobody is lying outright |
| `recruit catch-up` | one is working up to an ask, the other hasn't noticed |
| `confess catch-up` | one is trying to say something difficult and keeps not saying it |
| `persuade persuade` | an argument where neither is allowed to concede politely |
| `catch-up catch-up` | no agenda at all; the calm version |

Scenario and objectives are independent, so `--scenario hosting --objectives
confess catch-up` and `--scenario delayed-flight --objectives confess catch-up`
are the same pressure in very different rooms.

## The suspicion game

The default pairing — `--scenario online --objectives unmask unmask` — is an
adversarial framing layered on top of an ordinary chat. It's just one entry in
`objectives.md`, but it's the one the project was built around, so it's worth
describing in full. Both people are told:

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

Its `Reminder` re-states the defend-then-probe shape on every request, and its
`Notes` give each side two extra memory headings — the contradictions and
dodges they've caught, and the probes they've already burned — so the pressure
doesn't reset every time memory is condensed.

"Never admit you're an AI" lives in this objective, not in the general
conversation rules, so it doesn't leak into `catch-up` or `confess` runs where
it would be a strange thing to be told.

The `online` scenario is its natural partner: the two have never met and only
know each other from typing back and forth, so "what's around you right now"
and "describe your room" are real probes rather than non-sequiturs. It pairs
fine with the in-person scenarios too — `first-meeting` gives the accusation
somewhere much more awkward to happen.

## Adding your own

Nothing in the Python knows about any particular persona, scenario or
objective, so all three are added the same way: copy a block in the relevant
`.md` file and change it.

A new scenario needs a `Setting` and an `Opener`. Add `First` and `Second` only
if the two sides differ (one of them is hosting, one of them arrived late); add
`Knowledge` to say whether they're strangers, because without it two personas
will invent a shared past.

A new objective needs a `Goal`. Write it in the second person, give it a
concrete shape to follow, and say what counts as winning *and* losing. Add a
`Reminder` — one line, it's the difference between an objective the model
follows for three turns and one it follows for three hundred. Add `Notes` if
this person needs to remember something specific to keep the objective
coherent across a condense.

Placeholders: `{partner}` and `{speaker}` everywhere, plus `{owner}` (same
person as `{speaker}`) in a `Notes` section. A typo like `{partner_name}` fails
at load with a message naming the entry, rather than halfway through a run.

Check your work without spending any tokens:

```bash
python main.py --list      # it parsed, and the taglines read well
pytest                     # the shipped catalogues all load and render
```

The test suite loads `personas.md`, `scenarios.md` and `objectives.md` for
real, and fails if an entry is missing a required section, has no tagline, or
leaves an unfilled `{placeholder}` behind — so a broken block is caught there
rather than three turns into a run.

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

Every set of notes has the same three headings:

- **What `{owner}` told `{partner}` about themselves** — so the owner stays
  consistent with their own story.
- **What `{partner}` told `{owner}`** — the partner's checkable claims.
- **Open threads** — unanswered questions and anything left hanging.

On top of those, the owner's **objective** can add its own (the `Notes` section
in `objectives.md`). `unmask` adds *contradictions and dodges* and *probes
already used*; `interview` adds *questions already asked* and *what the owner
has given away*; `guarded` adds *the one thing being protected* and *how close
the other one has come*. The two speakers can therefore be keeping notes under
completely different headings in the same conversation.

It's told to record only what was actually said, never invented feelings or
motives, and to never write a "both agree" section — which keeps the notes
factual rather than editorializing.

`MEMORY_FIRST_PERSON` (default `True`) controls the voice:

- `True`: notes are written as the owner's own first-person notes ("I told
  Caleb about my walk; Caleb said his grandmother lives nearby").
- `False`: third person, but still organized from the owner's side.

If notes ever come back over `SUMMARY_MAX_WORDS`, they're recursively
re-summarized (up to `MAX_SHRINK_PASSES` times, each pass targeting 80% of
the limit) before being handed to the speaker; if compression stalls, they're
trimmed line-by-line as a last resort.

**What separate memories do and don't fix:** each person's notes emphasize
their own side, under headings their own objective chose, which helps them
stay consistent and stops them from silently inheriting the other's phrasing.
Both still heard the same transcript, so neither has private information about
what was *said*. What they do have privately is intent: the objective and its
reminder never appear in the transcript or in either memory, so a `guarded`
speaker's secret and a `recruit` speaker's ask are genuinely unknown to the
other side until they surface in conversation. Long-run drift (two characters
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

`transcript.txt` and `memory.txt` are **append-only** — opened in append mode,
flushed and `fsync`'d after every write, never truncated or rewritten,
including across separate runs. A crash can lose at most the message currently
mid-generation. `run_stats.json` is the opposite: a small snapshot, rewritten
in place every turn.

- **`transcript.txt`** — every message, in order. The session header records
  the setup, so a file with many runs in it stays readable:
  ```
  === New session | 2026-09-20T15:53:23 | Aisha & Jordan | hosting | recruit vs guarded ===

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

- **`run_stats.json`** — a snapshot of where the run stands, rewritten every
  turn, so a long unattended run can be checked on without reading the
  transcript. It records the setup (`speaker_a`/`speaker_b`, the models,
  `scenario`, `objective_a`/`objective_b`) alongside the counters:
  turns completed, empty replies, LLM errors, repetition regenerations, memory
  condenses, summarizer failures, forced drops, and `fatal_error` if the run
  stopped abnormally.

All three paths are configurable (`TRANSCRIPT_PATH`, `MEMORY_PATH`,
`STATS_PATH`) and resolved relative to wherever you run the script from.

## Configuration reference

Everything tunable lives in `config.py`, grouped and commented there. Summary:

| Setting | Default | What it does |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Where Ollama's chat API is |
| `NUM_CTX` | `8192` | Context window sent with every request. Too small and Ollama silently truncates the *start* of the prompt (the persona/rules), not the end — raise this if you raise the memory settings below |
| `MODEL_A` / `MODEL_B` | `llama3.2` | Models for the first / second speaker |
| `SUMMARIZER_MODEL` | `llama3.2` | Model used only for condensing memory |
| `PERSONAS_PATH` | `personas.md` | Who is talking. Resolved relative to the scripts if not absolute |
| `SCENARIOS_PATH` | `scenarios.md` | The settings catalogue |
| `OBJECTIVES_PATH` | `objectives.md` | The objectives catalogue |
| `SCENARIO` | `online` | Default setting; `--scenario` overrides it |
| `OBJECTIVE_A` / `OBJECTIVE_B` | `unmask` / `unmask` | Default objective per speaker, in persona order; `--objectives` overrides them |
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
| `STATS_PATH` | `run_stats.json` | Run-progress snapshot, rewritten every turn |

## File-by-file overview

| File | Responsibility |
|---|---|
| `main.py` | CLI entry point: argument parsing, the three picker menus, wires everything together |
| `config.py` | All tunables, described above |
| `catalog.py` | The shared `## Name` / `### Section` markdown parser, lookup and placeholder filling used by all three catalogues |
| `personas.py` | `Persona` + `load_personas` |
| `personas.md` | Who is talking — edit this to add/change people |
| `scenarios.py` | `Scenario` + `load_scenarios`; renders each speaker's own side of the setting |
| `scenarios.md` | Where they are — edit this to add/change settings |
| `objectives.py` | `Objective` + `load_objectives`; renders the goal, the private reminder and the memory headings |
| `objectives.md` | What each one wants — edit this to add/change objectives |
| `prompts.py` | Every prompt string: flow rules, the suspicion-game mission, summarizer/shrink prompts, script-mode framing |
| `conversation.py` | The main loop; reply cleaning (`clean_reply`, `strip_actions`); repetition scoring and retry logic |
| `memory.py` | `Turn`, `Summarizer` (condenses/shrinks notes via the LLM), `ConversationMemory` (verbatim buffer + per-person summaries) |
| `llm.py` | Thin Ollama client (`OllamaClient`) and `LLMError` — swap this file to use a different backend |
| `storage.py` | `AppendLog`, the crash-safe append-only file writer |
| `stats.py` | `RunStats` / `StatsLog` — the `run_stats.json` snapshot written each turn |
| `tests/` | `pytest` suite for the text and memory logic; no network, runs in under a second |

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

## Running the tests

```bash
pip install pytest
pytest
```

Everything is offline: the summarizer and speaker calls go through a fake
client, so the suite needs no Ollama server and finishes in well under a
second.

## Known limitations

- **Asymmetry is in intent, not in facts.** Objectives, reminders and memory
  headings are genuinely private, so the two sides want different things and
  remember under different headings. But both hear the exact same transcript,
  so neither knows a *fact* the other doesn't. A `guarded` speaker invents the
  thing they're protecting on the fly and holds it only in their own notes;
  nothing hands either side private world-state up front.
- **Long-run drift.** Because the running notes are rewritten (not appended)
  on every condense, a detail introduced early and never repeated can fade
  out of a person's memory over a very long conversation, while something
  vivid and recent dominates. Nothing pins a fact down except the fixed
  system prompt (bio, style, scenario) — anything that needs to be permanent
  should live there, not rely on surviving the summarizer indefinitely.
- **Small local models will sometimes ignore instructions** — an objective's
  shape (defend then probe; answer briefly then ask), its win/lose conditions,
  and the notes format are all things a 3B-class model will occasionally drop
  or garble. The `Reminder` section exists precisely because of this and helps
  a lot, but it doesn't fix it. `clean_reply` and the retry/shrink logic catch
  some of the rest.
- **Long objectives crowd out the persona.** The whole system prompt competes
  for the same attention: bio, style, setting, memory, rules, objective. A
  300-word objective on a 3B model will flatten the persona's voice. Keep new
  objectives about the length of the shipped ones.
- **The tests cover the pure logic only.** `pytest` exercises reply cleaning,
  repetition scoring, the memory buffer, the summarizer, the three catalogue
  loaders and the prompt wiring against a scripted fake model. `llm.py` (the
  HTTP layer) has no coverage, and nothing is tested against a live Ollama
  server — read a bit of `transcript.txt` and `memory.txt` after starting a
  fresh run before leaving it going unattended for a long time.

### Reverting to a relaxed conversation

This used to require editing `prompts.py`. It's now a flag:

```bash
python main.py --scenario old-friends --objectives catch-up
```

`catch-up` has no reminder and no extra memory headings, so nothing is pushing
the conversation anywhere. `old-friends` is the one scenario that lets them
assume a shared history rather than treating each other as strangers.
