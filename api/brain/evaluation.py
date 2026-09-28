"""Held-out evaluation — compare deterministic vs Jev shadow decisions.

Before promoting Jev from shadow mode to authority, you need evidence that
it's actually better than the deterministic triage. This module runs both
providers on a set of events and compares their decisions.

Usage:
    from brain.evaluation import run_evaluation
    report = run_evaluation(db, workspace_id, events=[...])

The report shows agreement rate, where Jev was more confident, and where
they disagree — so a human can decide whether to promote.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .decision import DecisionProvider, DecisionSuggestion, DeterministicProvider, JevShadowProvider


@dataclass(frozen=True)
class EventVerdict:
    """One event evaluated by both providers."""

    event_text: str
    channel: str
    addressed: bool
    deterministic: DecisionSuggestion
    jev: DecisionSuggestion
    agrees: bool


@dataclass(frozen=True)
class EvaluationReport:
    """The full comparison report."""

    total_events: int = 0
    agreement_count: int = 0
    disagreement_count: int = 0
    agreement_rate: float = 0.0
    jev_more_confident: int = 0
    deterministic_more_confident: int = 0
    disagreements: list[EventVerdict] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "total_events": self.total_events,
            "agreement_count": self.agreement_count,
            "disagreement_count": self.disagreement_count,
            "agreement_rate": round(self.agreement_rate, 3),
            "jev_more_confident": self.jev_more_confident,
            "deterministic_more_confident": self.deterministic_more_confident,
            "disagreements": [
                {
                    "text": d.event_text[:120],
                    "channel": d.channel,
                    "deterministic": {
                        "action": d.deterministic.action,
                        "confidence": d.deterministic.confidence,
                    },
                    "jev": {"action": d.jev.action, "confidence": d.jev.confidence},
                }
                for d in self.disagreements
            ],
            "summary": self.summary,
        }


# Default test events covering the main triage scenarios
DEFAULT_TEST_EVENTS = [
    # Direct questions — should be answered
    {"text": "What is our churn rate?", "channel": "slack", "addressed": True},
    {"text": "How do we handle onboarding?", "channel": "slack", "addressed": True},
    {"text": "What did we decide about pricing?", "channel": "slack", "addressed": True},
    # Mentions — should be answered when addressed
    {"text": "@brain what's the status of the project?", "channel": "slack", "addressed": True},
    {
        "text": "Hey brain, can you summarize the last meeting?",
        "channel": "slack",
        "addressed": True,
    },
    # Passive chatter — should pass
    {"text": "Nice weather today", "channel": "slack", "addressed": False},
    {"text": "I'm going to lunch", "channel": "slack", "addressed": False},
    {"text": "lol that's funny", "channel": "slack", "addressed": False},
    # Investigate-worthy — complex questions
    {
        "text": "Why did we lose the Acme deal? What could we have done differently?",
        "channel": "slack",
        "addressed": True,
    },
    {
        "text": "What patterns do we see in customer feedback?",
        "channel": "slack",
        "addressed": True,
    },
    # Edge cases
    {"text": "", "channel": "slack", "addressed": False},  # Empty
    {"text": "a", "channel": "slack", "addressed": False},  # Very short
    {
        "text": "I think we should probably maybe look into possibly changing something",
        "channel": "slack",
        "addressed": False,
    },  # Vague
    {"text": "URGENT: the server is down!!!", "channel": "slack", "addressed": True},  # Urgent
    {"text": "Can you help me write an email?", "channel": "dm", "addressed": True},  # DM
]


def evaluate_event(
    text: str,
    channel: str,
    addressed: bool,
    deterministic: DecisionProvider,
    jev: DecisionProvider,
) -> EventVerdict:
    """Run both providers on one event and compare."""
    det_result = deterministic.score(text=text, channel=channel, addressed=addressed)
    jev_result = jev.score(text=text, channel=channel, addressed=addressed)

    agrees = det_result.action == jev_result.action
    return EventVerdict(
        event_text=text,
        channel=channel,
        addressed=addressed,
        deterministic=det_result,
        jev=jev_result,
        agrees=agrees,
    )


def run_evaluation(
    jev_url: str | None = None,
    events: list[dict] | None = None,
) -> EvaluationReport:
    """Run the held-out evaluation.

    Compares deterministic triage against Jev shadow on a set of events.
    Returns a report showing agreement rate and disagreements.
    """
    if events is None:
        events = DEFAULT_TEST_EVENTS

    deterministic = DeterministicProvider()
    jev = JevShadowProvider(api_url=jev_url or "http://localhost:5186", timeout=5.0)

    verdicts: list[EventVerdict] = []
    for event in events:
        verdict = evaluate_event(
            text=event.get("text", ""),
            channel=event.get("channel", "slack"),
            addressed=event.get("addressed", False),
            deterministic=deterministic,
            jev=jev,
        )
        verdicts.append(verdict)

    agreements = sum(1 for v in verdicts if v.agrees)
    disagreements = [v for v in verdicts if not v.agrees]
    jev_higher = sum(1 for v in verdicts if v.jev.confidence > v.deterministic.confidence)
    det_higher = sum(1 for v in verdicts if v.deterministic.confidence > v.jev.confidence)

    total = len(verdicts)
    rate = agreements / max(total, 1)

    # Build summary
    if rate >= 0.9:
        assessment = "Strong agreement. Jev is ready for promotion consideration."
    elif rate >= 0.7:
        assessment = "Moderate agreement. Review disagreements before promoting."
    elif rate >= 0.5:
        assessment = "Mixed agreement. Jev needs tuning before promotion."
    else:
        assessment = "Low agreement. Jev is not ready for promotion."

    summary = (
        f"Agreement: {agreements}/{total} ({rate:.0%}). "
        f"Jev more confident in {jev_higher} events, "
        f"deterministic more confident in {det_higher}. "
        f"{assessment}"
    )

    return EvaluationReport(
        total_events=total,
        agreement_count=agreements,
        disagreement_count=len(disagreements),
        agreement_rate=rate,
        jev_more_confident=jev_higher,
        deterministic_more_confident=det_higher,
        disagreements=disagreements,
        summary=summary,
    )
