"""Deterministic triage of an inbound event.

The action a message gets is not the model's decision to make. Freeform output
is parsed against a fixed grammar, and any part of the decision the parse cannot
prove falls back to a rule computed from the text and the channel policy:

* The grammar is a whitelist. `ANSWER`, `INVESTIGATE` and `PASS` are the only
  actions, and an unparseable reply is not silently treated as one of them.
* Confidence is parsed, not averaged. A missing number is not evidence of high
  confidence, so it is replaced by the policy's floor for that kind of event.
* An explicit mention of the Brain outranks the model's refusal. Being named is
  a request for action, so a mention that asks a question can be upgraded to
  `investigate` but never downgraded to `pass`.
* `ANSWER` needs evidence. Below the evidence threshold it degrades to
  `investigate` rather than answering from whatever was handy.

The raw model output is carried separately as `private_raw`. Only the fields the
grammar defined are ever surfaced, which keeps stray chain-of-thought out of the
decision a user reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

TRIAGE_VERSION = "deterministic-triage-v1"

ACTIONS = ("answer", "investigate", "pass")

# Slack reaction names rather than emoji literals: the reaction is part of the
# protocol and belongs next to the action it acknowledges, not in a UI string.
REACTIONS = {"answer": "white_check_mark", "investigate": "mag", "pass": ""}

EVENT_KINDS = ("mention", "direct_message", "passive_message", "context_only", "ignored")

MODES = ("off", "mentions", "contextual", "proactive")

_MODE_KINDS: dict[str, frozenset[str]] = {
    "off": frozenset(),
    "mentions": frozenset({"mention", "direct_message"}),
    "contextual": frozenset({"mention", "direct_message", "passive_message"}),
    "proactive": frozenset({"mention", "direct_message", "passive_message", "context_only"}),
}

_FENCE = re.compile(r"```[A-Za-z0-9_-]*\n?|```")
_GRAMMAR = re.compile(r"^\s*(?P<action>ANSWER|INVESTIGATE|PASS)\b(?P<rest>.*)$", re.IGNORECASE)
_CONFIDENCE = re.compile(
    r"conf(?:idence)?\s*[=:]\s*(?P<value>0(?:\.\d+)?|1(?:\.0+)?)", re.IGNORECASE
)
_REASON = re.compile(r"(?:why|reason)\s*[=:]\s*(?P<value>.+)", re.IGNORECASE)
_ADDRESS = re.compile(r"(?:^|[\s\[(<])@?brain\b", re.IGNORECASE)
_DM_CHANNEL = re.compile(r"^(dm|im|mpim)[:_]", re.IGNORECASE)

_REQUEST_VERBS = (
    "add",
    "are",
    "can",
    "check",
    "compare",
    "could",
    "did",
    "do",
    "does",
    "draft",
    "explain",
    "find",
    "fix",
    "give",
    "help",
    "how",
    "is",
    "list",
    "log",
    "look",
    "note",
    "remind",
    "review",
    "should",
    "show",
    "summar",
    "tell",
    "track",
    "update",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "write",
)


@dataclass(frozen=True)
class ProactivityPolicy:
    """How much a channel may interrupt, and how sure the Brain must be.

    `answer_threshold` is separate from `min_confidence` on purpose: knowing
    which action to take is a lower bar than being allowed to answer without
    looking anything up.
    """

    mode: str = "mentions"
    min_confidence: float = 0.6
    answer_threshold: float = 0.75
    allow_investigate: bool = True
    react: bool = True

    @property
    def active_kinds(self) -> frozenset[str]:
        return _MODE_KINDS.get(self.mode, _MODE_KINDS["mentions"])

    def reacts_to(self, kind: str) -> bool:
        return kind in self.active_kinds

    def react_for(self, action: str) -> str:
        return REACTIONS.get(action, "") if self.react else ""


@dataclass(frozen=True)
class TriageParse:
    """What the grammar proved about a model reply."""

    action: str
    confidence: float | None
    reason: str


@dataclass(frozen=True)
class TriageDecision:
    """The action a turn will take, and why.

    `private_raw` holds the unparsed model output for debugging. It is never
    rendered to a user and never copied into `reason`.
    """

    action: str
    confidence: float
    reason: str
    source: str
    kind: str
    react: str
    private_raw: str = ""


def strip_fences(raw: str) -> str:
    return _FENCE.sub("", raw or "").strip()


def parse_triage(raw: str | None) -> TriageParse | None:
    """Read the first well-formed decision out of a model reply.

    Returns None when nothing in the reply matches the grammar. The caller must
    treat that as "no opinion", not as agreement, which is what keeps a chatty
    or truncated reply from steering the Brain.
    """
    if not raw:
        return None
    text = strip_fences(raw)
    if not text:
        return None
    for line in text.splitlines():
        match = _GRAMMAR.match(line)
        if match is None:
            continue
        rest = match.group("rest") or ""
        confidence = _CONFIDENCE.search(rest) or _CONFIDENCE.search(text)
        reason = _REASON.search(rest) or _REASON.search(text)
        return TriageParse(
            action=match.group("action").lower(),
            confidence=float(confidence.group("value")) if confidence else None,
            reason=(reason.group("value").strip()[:280] if reason else ""),
        )
    return None


def looks_like_request(text: str) -> bool:
    """Whether a message asks for something, judged from its opening words.

    Deliberately shallow: the first few tokens decide. Long verbs match on their
    stem, so "summarize" counts as "summar"; short words must match exactly, so
    "is" does not turn every sentence starting with "issue" into a request.
    """
    words = re.findall(r"[a-z']+", (text or "").lower())[:6]
    stems = tuple(verb for verb in _REQUEST_VERBS if len(verb) >= 5)
    if any(word in _REQUEST_VERBS or word.startswith(stems) for word in words):
        return True
    return "?" in (text or "") and len(words) >= 2


def classify_event(
    *,
    text: str,
    channel: str = "",
    addressed: bool = False,
    is_bot: bool = False,
) -> str:
    """Label an event by how the Brain relates to it.

    `ignored` is a real category, not a failure: the Brain's own output and
    other bots' messages are recorded and then left alone, so a reaction cannot
    make the Brain talk to itself.
    """
    if is_bot:
        return "ignored"
    body = (text or "").strip()
    if not body:
        return "ignored"
    if _DM_CHANNEL.match(channel or ""):
        return "direct_message"
    if addressed or _ADDRESS.search(body):
        return "mention"
    if looks_like_request(body):
        return "passive_message"
    return "context_only"


def decide_event(
    *,
    kind: str,
    text: str,
    policy: ProactivityPolicy,
    raw_output: str | None = None,
    evidence_strength: float = 0.0,
) -> TriageDecision:
    """Choose the action for one event.

    Order matters. Policy gates first (a quiet channel never acts), then the
    grammar, then the floors, then the evidence gate. Every downgrade records
    the rule that caused it, so a `pass` is explainable rather than mysterious.
    """
    if kind == "ignored":
        return TriageDecision(
            action="pass",
            confidence=1.0,
            reason="Not addressed to the Brain.",
            source="policy",
            kind=kind,
            react="",
            private_raw=raw_output or "",
        )
    if not policy.reacts_to(kind):
        return TriageDecision(
            action="pass",
            confidence=1.0,
            reason=f"Channel mode '{policy.mode}' does not react to {kind} events.",
            source="policy",
            kind=kind,
            react="",
            private_raw=raw_output or "",
        )

    addressed = kind in ("mention", "direct_message")
    asked = looks_like_request(text)
    parse = parse_triage(raw_output)

    if parse is None:
        # No grammar, no action. The one exception is a direct mention, which
        # never depended on triage to begin with: being named is the request.
        # A passive message with an unreadable reply stays silent, because
        # guessing at intent is the exact behavior the grammar exists to stop.
        if addressed:
            action = "investigate"
            confidence = 0.4
            reason = "No parseable decision; a direct mention is still answered."
        else:
            action = "pass"
            confidence = 0.0
            reason = "No parseable decision on a passive message; staying silent."
        source = "fallback"
    else:
        action = parse.action
        confidence = (
            parse.confidence if parse.confidence is not None else (0.7 if addressed else 0.5)
        )
        source = "grammar"
        reason = parse.reason or f"The reply chose {parse.action.upper()}."

    if confidence < policy.min_confidence:
        # Below the floor the Brain does not act on its own reading. A direct
        # mention is still answered with the cheap action rather than dropped.
        if addressed:
            action = "investigate"
            reason = (
                f"{reason} Confidence {confidence:.2f} is under the floor "
                f"{policy.min_confidence:.2f}, so this stays an investigation."
            )
        else:
            action = "pass"
            reason = (
                f"{reason} Confidence {confidence:.2f} is under the channel floor "
                f"{policy.min_confidence:.2f}."
            )
        source = f"{source}+floor"

    if action == "pass" and addressed and asked:
        # Affirmative override: being named and asked is a request, whatever the
        # reply said. Silence here is the failure mode users notice.
        action = "investigate"
        reason = f"{reason} A direct mention that asks for something outranks PASS."
        source = f"{source}+affirmative"

    if action == "answer" and evidence_strength < policy.answer_threshold:
        action = "investigate"
        reason = (
            f"{reason} Evidence {evidence_strength:.2f} is under the answer "
            f"threshold {policy.answer_threshold:.2f}, so look before answering."
        )
        source = f"{source}+evidence"

    if action == "investigate" and not policy.allow_investigate:
        action = "pass"
        reason = f"{reason} Investigation is disabled for this workspace."
        source = f"{source}+disabled"

    return TriageDecision(
        action=action,
        confidence=confidence,
        reason=reason[:600],
        source=source,
        kind=kind,
        react=policy.react_for(action),
        private_raw=raw_output or "",
    )


def with_mode(policy: ProactivityPolicy, mode: str) -> ProactivityPolicy:
    """A copy of a policy in another mode, used by the settings API."""
    if mode not in MODES:
        raise ValueError(f"Unknown proactivity mode: {mode}")
    return replace(policy, mode=mode)
