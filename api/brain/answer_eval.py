"""Score the brain against questions with known answers.

A retrieval or answering change is only an improvement if it answers more of
the person's own questions correctly and abstains on the ones it cannot
answer. Each `EvalQuestion` names the approved items a correct answer cites
(any one counts) or says the brain should abstain. A run asks every question
through the same `answer_question` path the console and agents use, under the
runner's own read scope, and reports:

- pass rate: answerable questions answered with an expected citation, plus
  abstain questions left unanswered;
- recall@k and MRR: whether an expected item is in the top k search results,
  and how high;
- false answers: abstain questions the brain answered anyway, the failure
  abstention exists to prevent;
- stale questions: expected items that are gone or no longer readable, so the
  question needs updating rather than counting as a retrieval miss.

Usage from a shell: `python -m brain.answer_eval [workspace-slug]`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import ReadScope
from .models import EvalQuestion, Knowledge, Workspace
from .services import answer_question, search_knowledge

TOP_K = 8


@dataclass
class QuestionResult:
    id: str
    question: str
    expect_abstain: bool
    expected_ids: list[str]
    passed: bool
    grounded: bool
    cited_ids: list[str]
    retrieved_ids: list[str]
    # 1-based rank of the first expected item in search results, if any.
    hit_rank: int | None
    stale_ids: list[str] = field(default_factory=list)
    reason: str = ""


def parse_ids(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except ValueError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def readable_ids(db: Session, scope: ReadScope, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return set(
        db.scalars(
            scope.apply(
                select(Knowledge.id).where(Knowledge.id.in_(ids), Knowledge.status == "canonical"),
                Knowledge,
            )
        )
    )


def score_question(
    db: Session, scope: ReadScope, row: EvalQuestion, *, write: bool = False, k: int = TOP_K
) -> QuestionResult:
    expected = parse_ids(row.expected_ids)
    live = readable_ids(db, scope, expected)
    stale = [i for i in expected if i not in live]
    retrieved = [item.id for item in search_knowledge(db, scope, row.question, limit=k)]
    result = answer_question(db, scope, row.question, write=write)
    cited = [citation.knowledge_id for citation in result.citations]
    hit_rank = next((rank for rank, i in enumerate(retrieved, start=1) if i in live), None)
    if row.expect_abstain:
        passed = not result.grounded
        reason = "" if passed else "Answered a question it should abstain on"
    elif not live:
        passed, reason = False, "Every expected item is gone or unreadable; update the question"
    elif not result.grounded:
        passed = False
        reason = (
            "Abstained; an expected item was retrieved but not used"
            if hit_rank
            else "Abstained; no expected item was retrieved"
        )
    else:
        passed = any(i in live for i in cited)
        reason = "" if passed else "Answered without citing an expected item"
    return QuestionResult(
        id=row.id,
        question=row.question,
        expect_abstain=row.expect_abstain,
        expected_ids=expected,
        passed=passed,
        grounded=result.grounded,
        cited_ids=cited,
        retrieved_ids=retrieved,
        hit_rank=hit_rank,
        stale_ids=stale,
        reason=reason,
    )


def summarize(results: list[QuestionResult], k: int = TOP_K) -> dict:
    answerable = [
        r for r in results if not r.expect_abstain and len(r.stale_ids) < len(r.expected_ids)
    ]
    abstain = [r for r in results if r.expect_abstain]

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 3) if whole else None

    return {
        "questions": len(results),
        "passed": sum(r.passed for r in results),
        "pass_rate": share(sum(r.passed for r in results), len(results)),
        "answerable": len(answerable),
        f"recall_at_{k}": share(sum(r.hit_rank is not None for r in answerable), len(answerable)),
        "mrr": (
            round(sum(1 / r.hit_rank for r in answerable if r.hit_rank) / len(answerable), 3)
            if answerable
            else None
        ),
        "answered_correctly": sum(r.passed for r in answerable),
        "abstain_questions": len(abstain),
        "abstained_correctly": sum(r.passed for r in abstain),
        "false_answers": sum(not r.passed for r in abstain),
        "stale_questions": sum(bool(r.stale_ids) for r in results),
    }


def run_eval(
    db: Session, scope: ReadScope, *, write: bool = False, k: int = TOP_K
) -> tuple[dict, list[QuestionResult]]:
    rows = list(
        db.scalars(
            select(EvalQuestion)
            .where(EvalQuestion.workspace_id == scope.workspace_id)
            .order_by(EvalQuestion.created_at)
        )
    )
    results = [score_question(db, scope, row, write=write, k=k) for row in rows]
    return summarize(results, k), results


def main(argv: list[str] | None = None) -> int:
    from .database import SessionLocal

    args = argv if argv is not None else sys.argv[1:]
    slug = args[0] if args else "default"
    with SessionLocal() as db:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
        if workspace is None:
            print(f"No workspace with slug {slug!r}", file=sys.stderr)
            return 2
        summary, results = run_eval(db, ReadScope(workspace.id, "owner"))
    print(json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
