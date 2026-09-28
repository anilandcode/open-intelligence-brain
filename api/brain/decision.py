"""Decision provider interface and Jev shadow adapter.

A DecisionProvider scores an incoming event and suggests an action. The
deterministic triage is always the authority — the provider is an opinion that
gets recorded but never overrides.

In shadow mode, the provider's suggestion is logged alongside the deterministic
decision so a human can compare and decide whether to promote it.

Usage:
    provider = JevShadowProvider(api_url="http://localhost:5186")
    suggestion = provider.score(text="Why did churn increase?", channel="slack")
    # suggestion.action == "answer", suggestion.confidence == 0.85
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger("brain.decision")


@dataclass(frozen=True)
class DecisionSuggestion:
    """A provider's opinion on what to do with an event."""
    action: str  # "answer", "investigate", "pass"
    confidence: float  # 0.0-1.0
    reason: str = ""
    provider: str = "unknown"
    metadata: dict = field(default_factory=dict)


class DecisionProvider(Protocol):
    """Interface for scoring events."""
    def score(self, *, text: str, channel: str, addressed: bool = False) -> DecisionSuggestion: ...


class DeterministicProvider:
    """The default provider — mirrors the deterministic triage rules.

    This exists so the provider interface is always satisfied, even when
    no external provider is configured.
    """
    name = "deterministic"

    def score(self, *, text: str, channel: str, addressed: bool = False) -> DecisionSuggestion:
        from .triage import ProactivityPolicy, classify_event, decide_event
        kind = classify_event(text=text, channel=channel, addressed=addressed, is_bot=False)
        policy = ProactivityPolicy()
        decision = decide_event(kind=kind, text=text, policy=policy)
        return DecisionSuggestion(
            action=decision.action,
            confidence=decision.confidence,
            reason=decision.reason,
            provider=self.name,
            metadata={"source": decision.source, "kind": kind},
        )


class JevShadowProvider:
    """Shadow-mode adapter for Jev decision scoring.

    Calls Jev's scoring endpoint and returns a suggestion. If Jev is
    unreachable or returns garbage, falls back to a neutral pass with
    confidence 0 — the deterministic triage still runs.

    Shadow mode means: record the suggestion, never act on it. A human
    reviews the comparison and decides whether to promote Jev to authority.
    """
    name = "jev-shadow"

    def __init__(self, api_url: str, timeout: float = 5.0):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def score(self, *, text: str, channel: str, addressed: bool = False) -> DecisionSuggestion:
        try:
            import httpx
            response = httpx.post(
                f"{self.api_url}/api/v1/score",
                json={"text": text, "channel": channel, "addressed": addressed},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return DecisionSuggestion(
                action=data.get("action", "pass"),
                confidence=float(data.get("confidence", 0.0)),
                reason=data.get("reason", ""),
                provider=self.name,
                metadata=data.get("metadata", {}),
            )
        except Exception as exc:
            logger.debug("Jev shadow scoring failed: %s", exc)
            return DecisionSuggestion(
                action="pass",
                confidence=0.0,
                reason=f"Jev unreachable: {exc}",
                provider=self.name,
                metadata={"error": str(exc)},
            )


def create_provider(jev_url: str | None = None) -> DecisionProvider:
    """Factory: return Jev shadow if configured, deterministic otherwise."""
    if jev_url:
        return JevShadowProvider(api_url=jev_url)
    return DeterministicProvider()