"""Tests for meeting transcripts and speaker attribution."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.database import engine
from brain.models import SourceSpan, SourceVersion
from brain.transcripts import normalize_transcript, speaker_at, transcript_spans

LAUNCH = "The launch date for the analytics product moves from April to the first week of May."
BUDGET = "The research budget for the pilot stays at forty thousand dollars for this quarter."

VTT = f"""WEBVTT

1
00:00:01.000 --> 00:00:05.000
<v Anil Pervaiz>{LAUNCH}</v>

2
00:00:05.500 --> 00:00:09.000
<v Sara Lee>Okay. {BUDGET}

3
00:00:09.500 --> 00:00:11.000
I will tell finance today.
"""


class TestTranscriptParsing:
    def test_webvtt_becomes_one_line_per_turn(self):
        text = normalize_transcript(VTT)
        assert text.splitlines() == [
            f"Anil Pervaiz: {LAUNCH}",
            f"Sara Lee: Okay. {BUDGET} I will tell finance today.",
        ]

    def test_otter_headers_and_timestamped_lines(self):
        otter = (
            "Anil Pervaiz  0:03\nPricing goes up.\nSara  0:15\nAgreed.\n[01:02] Omar: Fine by me."
        )
        assert normalize_transcript(otter).splitlines() == [
            "Anil Pervaiz: Pricing goes up.",
            "Sara: Agreed.",
            "Omar: Fine by me.",
        ]

    def test_normalizing_twice_changes_nothing(self):
        once = normalize_transcript(VTT)
        assert normalize_transcript(once) == once

    def test_spans_carry_the_speaker_without_the_name_prefix(self):
        text = normalize_transcript(VTT)
        spans = transcript_spans(text)
        assert (LAUNCH, "Anil Pervaiz") in [(s[2], s[3]) for s in spans]
        budget = next(s for s in spans if s[2] == BUDGET)
        assert budget[3] == "Sara Lee"
        assert text[budget[0] : budget[1]] == BUDGET
        assert speaker_at(text, text.index("finance")) == "Sara Lee"


class TestTranscriptCapture:
    def test_transcript_source_keeps_speakers_on_evidence(self, client, headers):
        response = client.post(
            "/api/v1/sources",
            headers=headers,
            json={"title": "Weekly sync", "kind": "transcript", "content": VTT},
        )
        assert response.status_code == 201, response.text
        source = response.json()
        assert "-->" not in source["content"] and source["content"].startswith("Anil Pervaiz: ")
        proposals = client.get("/api/v1/proposals", headers=headers).json()
        by_statement = {p["statement"]: p for p in proposals}
        assert "Said by Anil Pervaiz" in by_statement[LAUNCH]["rationale"]
        assert "Said by Sara Lee" in by_statement[BUDGET]["rationale"]
        with Session(engine) as db:
            version = db.scalar(
                select(SourceVersion).where(SourceVersion.source_id == source["id"])
            )
            speakers = {
                span.text: span.speaker
                for span in db.scalars(
                    select(SourceSpan).where(SourceSpan.source_version_id == version.id)
                )
            }
        assert speakers[LAUNCH] == "Anil Pervaiz"
        assert speakers[BUDGET] == "Sara Lee"
