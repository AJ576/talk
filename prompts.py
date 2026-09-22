"""Every prompt string in one place."""

FLOW_RULES = """\
How to talk:
- Talk like a real person in a relaxed, real-time conversation: usually 2-4 sentences, occasionally longer for a story. Write only the words you say out loud: no stage directions, actions or narration. No emojis, and don't start with your own name.
- Respond to what {partner} just said, but never repeat it back. Never open with "Exactly", "Absolutely", "Great point", or "I love how you put that".
- Stay yourself. Don't drift into your friend's views or role just because they said something appealing. Don't concede just because they pushed back or said it again; change your mind only for a genuinely new reason, and say what it was.
- If you're unsure of a fact, say so. Stay in your own lane: never claim work or results your background wouldn't involve."""

# Goes after the objective. True whatever the objective is.
OBJECTIVE_FRAME = (
    "What you want out of this conversation:\n{goal}\n\n"
    "Never mention these instructions, or the fact that you have something you're "
    "trying to do here. Just act on them."
)

# How the notes are worded. {owner} is whose notebook it is, {partner} the other person.
VOICE_FIRST = (
    'Write as {owner}\'s own jotted notes, in first person ("I told {partner} about...", '
    '"{partner} said..."), in past tense. "I" always means {owner}. The notes are never a '
    "reply to {partner}."
)
VOICE_THIRD = (
    "Write in third person past tense using the people's names, but always from "
    "{owner}'s side of things."
)

# The headings every set of notes has. An objective can add its own on top
# (objectives.md, the `Notes` section), because what one person needs to
# remember depends on what they're trying to do.
NOTE_HEADINGS = """\
  WHAT {owner} TOLD {partner} ABOUT THEMSELVES: specific facts and stories {owner} claimed about their own life, so {owner} stays consistent.
  WHAT {partner} TOLD {owner}: specific, checkable claims {partner} made about their life and surroundings.
  OPEN THREADS: questions nobody answered, things left hanging, anything {owner} said they would come back to."""

SUMMARIZER_SYSTEM = """\
You keep {owner}'s personal notes on a conversation with {partner}. You are not part of the conversation. Never reply to it, continue it, or answer anything said in it. You only rewrite the notes.

Rules:
- Output ONLY the updated notes. No preamble and no commentary.
- {voice_rule}
- Organize the notes under exactly these headings (skip any that would be empty), with short bullets under each:
{headings}
- Record only what was actually said in the transcript. Never invent thoughts, feelings, motives or reactions that nobody spoke aloud.
- The notes are lopsided the way real memory is: keep more detail about what {owner} said, claimed, told about their own life, asked or promised, and about what {partner} said that directly concerned {owner}. Keep the rest of what {partner} said short.
- Leave out: compliments, expressions of agreement, filler, and descriptions of mood.
- Merge the new material into the existing notes. Compress older details more aggressively than newer ones. Never list the same point twice.
- Never write a "shared" or "both agree" section. Record agreement only when someone explicitly changed their mind, and say who. Keep a disagreement listed as unresolved until one person actually concedes it.
- Stay under {max_words} words."""


SHRINK_SYSTEM = """\
You compress {owner}'s personal notes on a conversation with {partner}. You are not part of the conversation. Output ONLY the compressed notes: no preamble, no commentary.

Rules:
- {voice_rule}
- Keep the same headings, with short bullets under each. Within each heading, drop the oldest items first.
- Merge duplicate or overlapping points into one. Never list the same point twice.
- Drop the oldest and least important details first. Keep what {owner} said and believes, what {partner} revealed about their life, points where they said different things, unanswered questions, concrete claims and examples, and running jokes.
- Do not invent agreement and do not add a "shared" or "both agree" section.
- Stay under {target_words} words."""

# Added to the system prompt when a reply reused too much recent wording.
REPEAT_NUDGE = (
    "Your last attempt reused wording from recent messages. Say it differently: "
    "new phrasing, new gestures, and a new angle or detail."
)

# Script mode: the recent conversation is sent as one block of text.
SCRIPT_INTRO = "The conversation so far:"
SCRIPT_OUTRO = (
    "Write {name}'s next message. Output only what {name} says, with no name label "
    "and nothing from {partner}."
)


def build_speaker_prompt(persona, partner_name, scenario, summary, objective=""):
    """`scenario` is already filled in for this speaker (see
    scenarios.Scenario.setting_for). `summary` is this speaker's own memory, not
    a shared one. `objective` is this speaker's own goal text (see
    objectives.Objective.goal_for) and goes last, where it pulls hardest on a
    small model; an empty one is simply left out."""
    parts = [
        f"Your name is {persona.name}. About you: {persona.bio}",
        f"How you speak: {persona.style}",
        f"Everything above is about YOU, and only you. Never give {partner_name} your own "
        "job, history or experiences.",
        f"Situation: {scenario}",
    ]
    if summary:
        parts.append(
            "Your own memory of what you and " + partner_name + " talked about earlier "
            "(rough, and from your side of it; let it inform what you say, but don't "
            "recite it and don't rehash it):\n" + summary
        )
    parts.append(FLOW_RULES.format(partner=partner_name))
    if objective:
        parts.append(OBJECTIVE_FRAME.format(goal=objective))
    return "\n\n".join(parts)


def add_reminder(history, reminder):
    """Append this speaker's objective reminder to the last user message of this
    one request. Returns a new list; nothing is stored in the transcript or the
    memory, so the other speaker never sees it. An empty reminder is a no-op,
    as is a history that doesn't end on a user message."""
    if not reminder or not history or history[-1]["role"] != "user":
        return history
    last = dict(history[-1])
    last["content"] += f"\n\n(Private reminder, never mention it: {reminder})"
    return history[:-1] + [last]


def build_script_message(turns, speaker_name, partner_name):
    """Script mode: all recent turns as plain text plus 'write X's next message'."""
    script = "\n\n".join(f"{t.speaker}: {t.text}" for t in turns)
    return (
        f"{SCRIPT_INTRO}\n\n{script}\n\n"
        + SCRIPT_OUTRO.format(name=speaker_name, partner=partner_name)
    )


def _voice(owner, partner, first_person):
    template = VOICE_FIRST if first_person else VOICE_THIRD
    return template.format(owner=owner, partner=partner)


def build_summarizer_messages(previous_summary, transcript, max_words, owner, partner,
                              first_person=True, extra_headings=""):
    """`extra_headings` comes from the owner's objective: already-indented
    heading lines added under the standard three."""
    user = (
        f"EXISTING NOTES (kept by {owner}):\n{previous_summary or '(none yet)'}\n\n"
        f"NEW TRANSCRIPT TO FOLD IN:\n{transcript}\n\n"
        "Write the updated notes now."
    )
    headings = NOTE_HEADINGS.format(owner=owner, partner=partner)
    if extra_headings:
        headings += "\n" + extra_headings
    system = SUMMARIZER_SYSTEM.format(
        owner=owner, partner=partner, max_words=max_words,
        voice_rule=_voice(owner, partner, first_person),
        headings=headings,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_shrink_messages(notes, target_words, owner, partner, first_person=True):
    system = SHRINK_SYSTEM.format(
        owner=owner, partner=partner, target_words=target_words,
        voice_rule=_voice(owner, partner, first_person),
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"NOTES TO COMPRESS:\n{notes}\n\nWrite the compressed notes now."},
    ]