"""Triage rules, at the unit level.

Every test here pins a guard that keeps a language model from steering the
Brain: only three actions exist, only a grammatical reply is believed, and the
cheap failure modes (a mention that asks for something, an unproven answer) are
decided by rule rather than by the reply's own confidence.
"""

from brain.triage import (
    REACTIONS,
    ProactivityPolicy,
    classify_event,
    decide_event,
    looks_like_request,
    parse_triage,
)

QUESTION = "@brain what did we decide about enterprise pricing?"


def test_only_the_three_actions_are_parsed():
    parsed = parse_triage("INVESTIGATE conf=0.9 why=needs a lookup")
    assert parsed is not None
    assert (parsed.action, parsed.confidence, parsed.reason) == (
        "investigate",
        0.9,
        "needs a lookup",
    )
    # A chatty reply is not a decision. It must not be read as agreement.
    assert parse_triage("I think you should probably look into this one.") is None
    assert parse_triage("") is None
    assert parse_triage(None) is None


def test_a_fenced_reply_still_parses():
    parsed = parse_triage("Sure:\n```\nANSWER conf=0.8\nwhy=covered in the pricing note\n```")
    assert parsed is not None
    assert parsed.action == "answer"
    assert parsed.confidence == 0.8


def test_a_missing_confidence_is_not_read_as_certainty():
    parsed = parse_triage("ANSWER conf=high")
    assert parsed is not None and parsed.confidence is None
    decision = decide_event(
        kind="mention", text=QUESTION, policy=ProactivityPolicy(), raw_output="ANSWER conf=high"
    )
    # Falls back to the floor for an addressed event rather than to 1.0.
    assert decision.confidence == 0.7


def test_an_unparseable_reply_falls_back_to_the_text():
    decision = decide_event(
        kind="mention",
        text=QUESTION,
        policy=ProactivityPolicy(),
        raw_output="hmm, hard to say really",
    )
    assert decision.action == "investigate"
    assert decision.source.startswith("fallback")
    assert decision.confidence == 0.4


def test_an_unreadable_reply_leaves_a_passive_message_alone():
    # The reference runtime falls back to PASS when a triage reply cannot be
    # parsed, and the reason is worth keeping: an unreadable reply is the one
    # case where acting is indistinguishable from guessing.
    decision = decide_event(
        kind="passive_message",
        text="could you track the refund policy?",
        policy=ProactivityPolicy(mode="contextual"),
        raw_output="I'm not sure what you mean, honestly",
    )
    assert decision.action == "pass"
    assert decision.source.startswith("fallback")
    assert decision.confidence == 0.0


def test_a_direct_mention_that_asks_outranks_a_pass():
    decision = decide_event(
        kind="mention",
        text=QUESTION,
        policy=ProactivityPolicy(),
        raw_output="PASS conf=0.95 why=not worth the tokens",
    )
    assert decision.action == "investigate"
    assert decision.source.endswith("+affirmative")
    assert "outranks PASS" in decision.reason


def test_answering_needs_evidence_above_the_threshold():
    decision = decide_event(
        kind="mention",
        text=QUESTION,
        policy=ProactivityPolicy(),
        raw_output="ANSWER conf=0.95",
        evidence_strength=0.1,
    )
    assert decision.action == "investigate"
    assert decision.source.endswith("+evidence")
    assert "Evidence 0.10" in decision.reason

    proven = decide_event(
        kind="mention",
        text=QUESTION,
        policy=ProactivityPolicy(),
        raw_output="ANSWER conf=0.95",
        evidence_strength=0.9,
    )
    assert proven.action == "answer"
    assert proven.source == "grammar"


def test_low_confidence_on_an_ambient_message_stays_quiet():
    decision = decide_event(
        kind="passive_message",
        text="The billing rewrite might land next week.",
        policy=ProactivityPolicy(mode="contextual"),
        raw_output="ANSWER conf=0.2",
    )
    assert decision.action == "pass"
    assert decision.source.endswith("+floor")


def test_channel_mode_gates_before_the_model_is_consulted():
    decision = decide_event(
        kind="mention",
        text=QUESTION,
        policy=ProactivityPolicy(mode="off"),
        raw_output="INVESTIGATE conf=1.0 why=certain",
    )
    assert decision.action == "pass"
    assert decision.source == "policy"
    assert decision.reason == "Channel mode 'off' does not react to mention events."
    assert decision.react == ""


def test_investigation_can_be_disabled_workspace_wide():
    decision = decide_event(
        kind="mention",
        text=QUESTION,
        policy=ProactivityPolicy(allow_investigate=False),
        raw_output="INVESTIGATE conf=0.9",
    )
    assert decision.action == "pass"
    assert decision.source.endswith("+disabled")


def test_event_kinds_are_classified_from_the_channel_and_the_text():
    assert classify_event(text=QUESTION, channel="#eng", addressed=True) == "mention"
    assert classify_event(text=QUESTION, channel="#eng") == "mention"
    assert classify_event(text="any text", channel="dm:anil") == "direct_message"
    assert classify_event(text="Bot output", channel="#eng", is_bot=True) == "ignored"
    assert classify_event(text="   ", channel="#eng") == "ignored"
    assert classify_event(text="The deploy finished at noon.", channel="#eng") == "context_only"
    assert (
        classify_event(text="could you track the refund policy?", channel="#eng")
        == "passive_message"
    )


def test_request_detection_is_shallow_on_purpose():
    assert looks_like_request("what did we decide?")
    assert looks_like_request("summarize last week")
    assert not looks_like_request("The deploy finished at noon.")


def test_reactions_are_protocol_names_not_emoji():
    assert REACTIONS["answer"] == "white_check_mark"
    assert REACTIONS["investigate"] == "mag"
    assert ProactivityPolicy(react=False).react_for("answer") == ""


def test_raw_model_output_is_carried_but_never_spoken():
    raw = "PASS secret chain-of-thought XYZ"
    decision = decide_event(
        kind="passive_message",
        text="The deploy finished at noon.",
        policy=ProactivityPolicy(mode="contextual"),
        raw_output=raw,
    )
    assert "XYZ" not in decision.reason
    assert decision.private_raw == raw
