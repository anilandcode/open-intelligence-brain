"""Critic pass — a separately labeled model opinion on proposal quality.

The critic reviews each proposal after extraction and flags:
- Evidence gaps: claims that are too broad for their source excerpt
- Missing specificity: vague language that should be sharpened
- Type mismatch: a "fact" that reads like a "belief" or vice versa
- Weak sourcing: excerpts that don't clearly support the claim

The critic never blocks — it only adds signals. A proposal with critic
notes still enters the review queue; the human decides whether to approve,
reject, or edit.

This is the one remaining M3 item: a labeled model opinion that helps
reviewers make faster, better decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CriticNote:
    """One observation from the critic pass."""

    severity: str  # "info", "warning", "strong"
    category: str  # "evidence_gap", "specificity", "type_mismatch", "weak_sourcing"
    message: str


@dataclass(frozen=True)
class CriticAssessment:
    """The full critic assessment for a proposal."""

    proposal_id: str
    notes: list[CriticNote] = field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0, how confident the critic is in its assessment

    @property
    def has_notes(self) -> bool:
        return len(self.notes) > 0

    @property
    def warning_count(self) -> int:
        return sum(1 for n in self.notes if n.severity in ("warning", "strong"))

    def summary(self) -> str:
        if not self.notes:
            return "No issues found."
        parts = []
        for note in self.notes:
            prefix = {"info": "ℹ", "warning": "⚠", "strong": "🔴"}.get(note.severity, "•")
            parts.append(f"{prefix} {note.message}")
        return "\n".join(parts)


# Vague phrases that suggest the claim needs sharpening
_VAGUE_PATTERNS = [
    (r"\b(?:a lot|many|some|several|various|numerous)\b", "Quantify: how many exactly?"),
    (r"\b(?:often|sometimes|usually|generally|typically)\b", "Specify: how frequently?"),
    (r"\b(?:good|bad|better|worse|important|significant)\b", "Define: what makes it {word}?"),
    (r"\b(?:things|stuff|something)\b", "Name the specific thing."),
    (r"\b(?:everyone|nobody|always|never)\b", "Is this truly universal? Qualify if not."),
    (r"\b(?:might|could|may|perhaps|possibly)\b", "Is this a hypothesis or a finding?"),
]

# Patterns that suggest the claim exceeds its evidence
_BROAD_CLAIM_PATTERNS = [
    (
        r"\b(?:all|every|each)\s+\w+\s+(?:is|are|should|must|will)\b",
        "Universal claim — does the excerpt support 'all'?",
    ),
    (
        r"\b(?:the\s+best|the\s+only|the\s+most|the\s+worst)\b",
        "Superlative — is this the strongest defensible wording?",
    ),
    (
        r"\b(?:always|never|impossible|cannot)\b",
        "Absolute — does the evidence rule out exceptions?",
    ),
    (
        r"\b(?:proves?|demonstrates?|shows?)\s+that\b",
        "Causal claim — does the excerpt actually show causation?",
    ),
]


def _check_specificity(statement: str) -> list[CriticNote]:
    """Flag vague language that could be sharpened."""
    notes = []
    lowered = statement.lower()
    for pattern, message_template in _VAGUE_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            word = match.group(0)
            message = message_template.replace("{word}", word)
            notes.append(
                CriticNote(
                    severity="info",
                    category="specificity",
                    message=message,
                )
            )
    return notes


def _check_evidence_gap(statement: str, excerpt: str) -> list[CriticNote]:
    """Flag claims that seem broader than their evidence."""
    notes = []
    if not excerpt:
        notes.append(
            CriticNote(
                severity="warning",
                category="weak_sourcing",
                message="No source excerpt — reviewer cannot verify the claim against its evidence.",
            )
        )
        return notes

    for pattern, message in _BROAD_CLAIM_PATTERNS:
        if re.search(pattern, statement, re.IGNORECASE):
            # Check if the excerpt actually contains supporting language
            excerpt_lower = excerpt.lower()
            # If the claim is broad but the excerpt uses hedging language, flag it
            hedging = re.search(
                r"\b(?:suggests?|indicates?|appears?|seems?|may|might|could)\b", excerpt_lower
            )
            if hedging:
                notes.append(
                    CriticNote(
                        severity="warning",
                        category="evidence_gap",
                        message=f"{message} The source excerpt uses hedging language ('{hedging.group(0)}').",
                    )
                )
            else:
                notes.append(
                    CriticNote(
                        severity="info",
                        category="evidence_gap",
                        message=message,
                    )
                )

    # Check if the statement is much longer than the excerpt (potential over-extraction)
    if len(statement) > len(excerpt) * 2 and len(statement) > 200:
        notes.append(
            CriticNote(
                severity="warning",
                category="evidence_gap",
                message="The statement is much longer than its source excerpt — is it adding interpretation?",
            )
        )

    return notes


def _check_type_mismatch(statement: str, declared_type: str) -> list[CriticNote]:
    """Flag statements whose language doesn't match their declared type."""
    notes = []
    lowered = statement.lower()

    # A "fact" that reads like a belief
    if declared_type == "fact":
        belief_markers = ["believe", "think", "feel", "should", "ought", "prefer"]
        if any(marker in lowered for marker in belief_markers):
            notes.append(
                CriticNote(
                    severity="info",
                    category="type_mismatch",
                    message="Declared as 'fact' but reads like a belief or opinion.",
                )
            )

    # A "belief" that reads like a data-backed claim
    if declared_type == "belief":
        evidence_markers = ["data shows", "research shows", "measured", "study found", "statistics"]
        if any(marker in lowered for marker in evidence_markers):
            notes.append(
                CriticNote(
                    severity="info",
                    category="type_mismatch",
                    message="Declared as 'belief' but cites evidence — consider reclassifying as 'evidence'.",
                )
            )

    # A "question" that isn't actually a question
    if declared_type == "question" and "?" not in statement:
        question_starters = ["how to", "what is", "why do", "when should"]
        if not any(s in lowered for s in question_starters):
            notes.append(
                CriticNote(
                    severity="info",
                    category="type_mismatch",
                    message="Declared as 'question' but doesn't read as one.",
                )
            )

    return notes


def _check_excerpt_coverage(statement: str, excerpt: str) -> list[CriticNote]:
    """Check if key terms from the statement appear in the excerpt."""
    notes = []
    if not excerpt:
        return notes

    # Extract significant terms from the statement
    stop = {
        "the",
        "and",
        "are",
        "for",
        "that",
        "this",
        "with",
        "from",
        "but",
        "not",
        "you",
        "all",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
    }
    statement_terms = {t for t in re.findall(r"[a-z]{3,}", statement.lower()) if t not in stop}
    excerpt_terms = {t for t in re.findall(r"[a-z]{3,}", excerpt.lower()) if t not in stop}

    if not statement_terms:
        return notes

    coverage = len(statement_terms & excerpt_terms) / len(statement_terms)
    if coverage < 0.3 and len(statement_terms) >= 3:
        notes.append(
            CriticNote(
                severity="strong",
                category="weak_sourcing",
                message=f"Only {coverage:.0%} of key terms in the statement appear in the excerpt — is this the right source?",
            )
        )
    elif coverage < 0.5 and len(statement_terms) >= 4:
        notes.append(
            CriticNote(
                severity="warning",
                category="weak_sourcing",
                message=f"Low excerpt coverage ({coverage:.0%}) — some claims may not be supported by this source.",
            )
        )

    return notes


def assess_proposal(
    proposal_id: str,
    statement: str,
    declared_type: str,
    source_excerpt: str = "",
) -> CriticAssessment:
    """Run the critic pass on a proposal.

    Returns an assessment with notes but never blocks. The human reviewer
    sees the notes and decides.
    """
    notes: list[CriticNote] = []

    notes.extend(_check_specificity(statement))
    notes.extend(_check_evidence_gap(statement, source_excerpt))
    notes.extend(_check_type_mismatch(statement, declared_type))
    notes.extend(_check_excerpt_coverage(statement, source_excerpt))

    # Deduplicate by (category, message)
    seen = set()
    unique_notes = []
    for note in notes:
        key = (note.category, note.message)
        if key not in seen:
            seen.add(key)
            unique_notes.append(note)

    # Confidence: higher when we found issues
    has_warnings = any(n.severity in ("warning", "strong") for n in unique_notes)
    confidence = 0.8 if has_warnings else (0.5 if unique_notes else 0.3)

    return CriticAssessment(
        proposal_id=proposal_id,
        notes=unique_notes,
        confidence=confidence,
    )
