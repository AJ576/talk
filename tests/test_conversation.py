"""Tests for the pure-text helpers in conversation.py: clean_reply, strip_actions
and repetition_score. None of these touch the network or Ollama."""

from conversation import clean_reply, repetition_score, strip_actions


# ---------------------------------------------------------------------------
# strip_actions
# ---------------------------------------------------------------------------

def test_strip_actions_removes_a_single_action():
    assert strip_actions("*sighs* I don't know.") == "I don't know."


def test_strip_actions_removes_action_in_the_middle():
    assert strip_actions("Well, *leans back and laughs* that's a lot.") == "Well, that's a lot."


def test_strip_actions_unwraps_bold_instead_of_deleting_it():
    assert strip_actions("This is **really** important.") == "This is really important."


def test_strip_actions_handles_an_action_cut_off_by_truncation():
    # no closing '*' -- the model got cut off mid-action, so the fragment goes
    assert strip_actions("Sure, *leans in and starts", truncated=True) == "Sure,"


def test_strip_actions_keeps_text_after_a_stray_asterisk_when_not_truncated():
    # the model chose to end here, so the '*' is a stray character, not the
    # start of an action; dropping the rest would lose real content
    assert strip_actions("It cost 5 * 3 dollars, roughly.") == "It cost 5 3 dollars, roughly."


def test_strip_actions_leaves_an_unclosed_action_mid_text_as_prose():
    # nothing marks where an unclosed action ends, so only the '*' is removed
    assert strip_actions("Sure, *leans in and keeps talking.") == "Sure, leans in and keeps talking."


def test_strip_actions_leaves_plain_text_alone():
    text = "Nothing weird here at all."
    assert strip_actions(text) == text


# ---------------------------------------------------------------------------
# clean_reply
# ---------------------------------------------------------------------------

def test_clean_reply_strips_leading_name_prefix():
    assert clean_reply("Lena: hey, how's it going?", "Lena") == "Hey, how's it going?"


def test_clean_reply_name_prefix_is_case_insensitive():
    assert clean_reply("lena:  hi there", "Lena") == "Hi there"


def test_clean_reply_strips_filler_agreement_opener():
    text = clean_reply("Exactly, that's what I was thinking.", "Lena")
    assert not text.lower().startswith("exactly")
    assert "that's what i was thinking" in text.lower()


def test_clean_reply_strips_ah_yes_style_opener():
    text = clean_reply("Ah, yes! I get that completely.", "Lena")
    assert not text.lower().startswith("ah")


def test_clean_reply_does_not_gut_a_reply_that_is_only_agreement():
    # stripping the filler opener would leave nothing useful, so the loop in
    # clean_reply should stop rather than erase the whole reply down to "."
    text = clean_reply("Absolutely.", "Lena")
    assert text  # not empty


def test_clean_reply_removes_stock_praise():
    text = clean_reply(
        "I love how you put that. Anyway, the tide was rough that day.", "Lena"
    )
    assert "love how you put that" not in text.lower()
    assert "tide was rough" in text.lower()


def test_clean_reply_unwraps_a_fully_quoted_reply():
    assert clean_reply('"This is the whole message."', "Lena") == "This is the whole message."


def test_clean_reply_leaves_a_partial_quote_alone():
    text = clean_reply('She said "hello" to me.', "Lena")
    assert text == 'She said "hello" to me.'


def test_clean_reply_strips_action_stage_directions():
    text = clean_reply("*sighs* I don't know what to tell you.", "Lena")
    assert "*" not in text
    assert "sighs" not in text.lower()


def test_clean_reply_capitalizes_the_first_letter():
    assert clean_reply("well, that's one way to put it.", "Lena").startswith("Well")


def test_clean_reply_collapses_extra_whitespace():
    text = clean_reply("Lena: hi    there   friend", "Lena")
    assert "  " not in text


def test_clean_reply_cuts_off_a_line_where_the_partner_starts_talking():
    # script mode: the model kept going and started writing the other person's line
    text = clean_reply(
        "That sounds about right.\n\nDev: and I think you're wrong about that",
        "Lena", partner="Dev",
    )
    assert "Dev" not in text
    assert "wrong about that" not in text


def test_clean_reply_partner_cutoff_is_case_insensitive():
    text = clean_reply("Sure thing.\ndev: no way", "Lena", partner="Dev")
    assert text == "Sure thing."


def test_clean_reply_without_partner_leaves_embedded_name_alone():
    # no `partner` given -> no cutoff should happen at all
    text = clean_reply("Sure thing.\nDev: no way", "Lena")
    assert "Dev: no way" in text


def test_clean_reply_drops_a_truncated_trailing_fragment():
    text = clean_reply(
        "I think the real issue is trust. It's not about the mo",
        "Lena", truncated=True,
    )
    assert text == "I think the real issue is trust."


def test_clean_reply_keeps_a_truncated_reply_that_still_ends_cleanly():
    text = clean_reply("I think the real issue is trust.", "Lena", truncated=True)
    assert text == "I think the real issue is trust."


def test_clean_reply_does_not_trim_an_untruncated_reply():
    # truncated=False (the default): a dangling fragment is left as-is, since
    # the model chose to end there rather than being cut off.
    text = clean_reply("I think the real issue is trust and also", "Lena")
    assert text.endswith("and also")


# ---------------------------------------------------------------------------
# repetition_score
# ---------------------------------------------------------------------------

def test_repetition_score_is_zero_for_short_replies():
    # fewer than 8 four-word phrases -> always scored 0, regardless of overlap
    assert repetition_score("hi there friend", ["hi there friend how are you"]) == 0.0


def test_repetition_score_is_zero_with_no_overlap():
    mine = "the quick brown fox jumps over the lazy dog every single morning without fail"
    recent = ["completely unrelated words about sailing boats and weather patterns today"]
    assert repetition_score(mine, recent) == 0.0


def test_repetition_score_is_one_for_an_exact_repeat():
    text = "the quick brown fox jumps over the lazy dog near the old wooden fence"
    assert repetition_score(text, [text]) == 1.0


def test_repetition_score_is_partial_for_partial_overlap():
    mine = "the quick brown fox jumps over the lazy dog by the river every day"
    recent = ["the quick brown fox jumps over the lazy dog but not today at all"]
    score = repetition_score(mine, recent)
    assert 0.0 < score < 1.0


def test_repetition_score_checks_against_either_speaker():
    mine = "the quick brown fox jumps over the lazy dog near the old barn today"
    recent_a = "totally different sentence about something else entirely happening now"
    recent_b = "the quick brown fox jumps over the lazy dog near the old barn today"
    assert repetition_score(mine, [recent_a, recent_b]) == 1.0


def test_repetition_score_is_case_insensitive():
    mine = "The Quick Brown Fox Jumps Over The Lazy Dog Near The Old Fence Today"
    recent = ["the quick brown fox jumps over the lazy dog near the old fence today"]
    assert repetition_score(mine, recent) == 1.0


def test_clean_reply_strips_a_name_prefix_hidden_behind_an_action():
    # the action is removed first, so the prefix is at the front by the time
    # it is looked for
    assert clean_reply("*smiles* Lena: hi there", "Lena") == "Hi there"


def test_clean_reply_strips_a_stacked_name_prefix():
    assert clean_reply("Lena: Lena: hi there", "Lena") == "Hi there"


def test_clean_reply_cuts_the_partner_off_mid_line():
    # the model finished a sentence and carried straight on as the other person
    assert clean_reply("Sure. Dev: no way", "Lena", partner="Dev") == "Sure."


def test_clean_reply_leaves_a_partner_name_used_in_a_sentence():
    # not a new line and not a new sentence -- this is Lena quoting herself
    text = clean_reply("I told Dev: bring wine.", "Lena", partner="Dev")
    assert text == "I told Dev: bring wine."


def test_clean_reply_does_not_cut_when_the_whole_reply_is_the_partner_label():
    # nothing before the label, so there is nothing to keep; leave it to the
    # other cleaners rather than returning an empty reply
    assert clean_reply("Dev: no way", "Lena", partner="Dev")


def test_clean_reply_capitalizes_after_unwrapping_quotes():
    assert clean_reply('"this is the whole message."', "Lena") == "This is the whole message."


def test_clean_reply_keeps_a_stray_asterisk_reply_intact():
    text = clean_reply("It cost 5 * 3 dollars, roughly.", "Lena")
    assert "3 dollars, roughly." in text
