"""Meeting transcripts: who said what, kept on every evidence span.

Transcripts arrive in many shapes: a WebVTT or SRT caption file from Zoom,
Teams or Meet, an Otter export with the speaker on its own line, or a plain
"Name: text" paste. ``normalize_transcript`` turns all of them into one
"Name: text" line per turn and drops caption numbers and timings, so the
source the reviewer reads is the conversation itself. ``transcript_spans``
then cuts each turn into sentence spans that carry the speaker, so an
approved fact can always say whose words it rests on.
"""

from __future__ import annotations

import re

_TIMING = re.compile(
    r"^\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?\s*-->\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?.*$"
)
_CUE_NUMBER = re.compile(r"^\s*\d+\s*$")
_VOICE_TAG = re.compile(r"^\s*<v(?:\.[^ >]*)?\s+([^>]+)>(.*?)(?:</v>)?\s*$")
_TAGS = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
_STAMP = r"\[?\(?\d{1,2}:\d{2}(?::\d{2})?\)?\]?"
_NAME = r"[A-Z][\w.'’-]*(?: [A-Z][\w.'’-]*){0,3}"
# "Anil Pervaiz  0:03" or "Anil Pervaiz 00:01:12" alone on a line (Otter, Meet).
_SPEAKER_HEADER = re.compile(rf"^\s*({_NAME})\s+{_STAMP}\s*$")
# "[00:12] Anil: text", "Anil (00:12): text" or "Anil: text".
_TURN = re.compile(rf"^\s*(?:{_STAMP}\s*)?({_NAME})(?:\s*{_STAMP})?\s*:\s+(?=\S)")
_LEADING_STAMP = re.compile(rf"^\s*{_STAMP}\s*")
_NOT_NAMES = frozenset(
    {"Note", "Notes", "Action", "Actions", "Decision", "Todo", "Summary", "Agenda"}
)


def _speaker(match: re.Match) -> str | None:
    name = match.group(1).strip()
    return None if name in _NOT_NAMES else name


def normalize_transcript(text: str) -> str:
    """One "Name: text" line per turn; caption headers, numbers and timings dropped."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    current: str | None = None
    for raw in lines:
        line = raw.strip()
        if (
            not line
            or line == "WEBVTT"
            or line.startswith(("NOTE ", "STYLE", "Kind:", "Language:"))
        ):
            continue
        if _TIMING.match(line) or _CUE_NUMBER.match(line):
            continue
        voice = _VOICE_TAG.match(line)
        if voice:
            current = voice.group(1).strip()
            body = _TAGS.sub("", voice.group(2)).strip()
            if body:
                out.append(f"{current}: {body}")
            continue
        line = _TAGS.sub("", line).strip()
        header = _SPEAKER_HEADER.match(line)
        if header and _speaker(header):
            current = header.group(1).strip()
            continue
        turn = _TURN.match(line)
        if turn and _speaker(turn):
            current = turn.group(1).strip()
            out.append(f"{current}: {line[turn.end() :].strip()}")
            continue
        line = _LEADING_STAMP.sub("", line)
        if not line:
            continue
        # A line that continues the same caption or turn joins the speaker's line.
        if current and out and out[-1].startswith(f"{current}: "):
            out[-1] = f"{out[-1]} {line}"
        elif current:
            out.append(f"{current}: {line}")
        else:
            out.append(line)
    return "\n".join(out)


def transcript_spans(content: str) -> list[tuple[int, int, str, str | None]]:
    """Sentence spans of a transcript, each with the speaker of its turn.

    Offsets index the stored content. The "Name:" prefix stays out of the span
    text, so the evidence is the speaker's own words.
    """
    from .services import extract_spans

    spans: list[tuple[int, int, str, str | None]] = []
    offset = 0
    speaker: str | None = None
    for line in content.split("\n"):
        body_start = 0
        turn = _TURN.match(line)
        if turn and _speaker(turn):
            speaker = turn.group(1).strip()
            body_start = turn.end()
        for start, end, text in extract_spans(line[body_start:]):
            spans.append((offset + body_start + start, offset + body_start + end, text, speaker))
        offset += len(line) + 1
    return spans


def speaker_at(content: str, position: int) -> str | None:
    """The speaker whose turn contains `position` (the same rule as the spans)."""
    speaker: str | None = None
    offset = 0
    for line in content.split("\n"):
        turn = _TURN.match(line)
        if turn and _speaker(turn):
            speaker = turn.group(1).strip()
        offset += len(line) + 1
        if position < offset:
            break
    return speaker
