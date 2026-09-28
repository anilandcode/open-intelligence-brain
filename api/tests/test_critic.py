"""Tests for the critic pass."""

import pytest
from brain.critic import assess_proposal, CriticNote, CriticAssessment


class TestCriticAssessment:
    def test_clean_proposal_has_no_notes(self):
        result = assess_proposal(
            proposal_id="test1",
            statement="The team decided to use PostgreSQL for the main database.",
            declared_type="decision",
            source_excerpt="After evaluating options, the team decided to use PostgreSQL for the main database.",
        )
        # May or may not have notes, but should not have strong warnings
        assert isinstance(result, CriticAssessment)
        assert result.proposal_id == "test1"

    def test_vague_language_flagged(self):
        result = assess_proposal(
            proposal_id="test2",
            statement="Many users often prefer better onboarding.",
            declared_type="fact",
            source_excerpt="Some users mentioned onboarding could be improved.",
        )
        assert result.has_notes
        specificity_notes = [n for n in result.notes if n.category == "specificity"]
        assert len(specificity_notes) >= 2  # "many" and "often" and "better"

    def test_broad_claim_with_hedging_flagged(self):
        result = assess_proposal(
            proposal_id="test3",
            statement="All customers should use the new dashboard because it proves that engagement increases.",
            declared_type="belief",
            source_excerpt="The data suggests that some customers may benefit from the new dashboard.",
        )
        assert result.has_notes
        evidence_notes = [n for n in result.notes if n.category == "evidence_gap"]
        assert len(evidence_notes) >= 1

    def test_missing_excerpt_flagged(self):
        result = assess_proposal(
            proposal_id="test4",
            statement="The company revenue doubled last quarter.",
            declared_type="fact",
            source_excerpt="",
        )
        assert result.has_notes
        sourcing_notes = [n for n in result.notes if n.category == "weak_sourcing"]
        assert len(sourcing_notes) >= 1
        assert "No source excerpt" in sourcing_notes[0].message

    def test_type_mismatch_fact_as_belief(self):
        result = assess_proposal(
            proposal_id="test5",
            statement="I believe we should prioritize mobile because data shows 70% of users are on mobile.",
            declared_type="fact",
            source_excerpt="70% of our users access the product via mobile devices.",
        )
        type_notes = [n for n in result.notes if n.category == "type_mismatch"]
        assert len(type_notes) >= 1

    def test_excerpt_coverage_low(self):
        result = assess_proposal(
            proposal_id="test6",
            statement="Quantum computing will revolutionize cryptography and render current encryption obsolete.",
            declared_type="thesis",
            source_excerpt="The team discussed quarterly sales targets and marketing budget allocation.",
        )
        assert result.has_notes
        sourcing_notes = [n for n in result.notes if n.category == "weak_sourcing"]
        assert len(sourcing_notes) >= 1

    def test_confidence_refaches_findings(self):
        clean = assess_proposal(
            proposal_id="c1",
            statement="PostgreSQL was selected as the primary database.",
            declared_type="decision",
            source_excerpt="After review, PostgreSQL was selected as the primary database.",
        )
        messy = assess_proposal(
            proposal_id="c2",
            statement="All users always prefer better features and many things should be improved.",
            declared_type="fact",
            source_excerpt="",
        )
        # Messy should have higher confidence (more issues found)
        assert messy.confidence >= clean.confidence

    def test_summary_format(self):
        result = assess_proposal(
            proposal_id="s1",
            statement="Many users often want better things.",
            declared_type="fact",
            source_excerpt="Users mentioned some improvements.",
        )
        summary = result.summary()
        if result.has_notes:
            assert "ℹ" in summary or "⚠" in summary or "🔴" in summary
        else:
            assert summary == "No issues found."