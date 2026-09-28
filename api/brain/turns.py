"""Turn orchestration: triage an event, then run, steer, stop, or resume it.

A turn is the unit of agency in the Brain, and it is deliberately boring:

* It is a row, not a process. Nothing here spawns a worker, so a turn waiting on
  an approval survives a restart and resumes from its stored checkpoint rather
  than from memory.
* Its budget is a column. A turn that has spent its steps stops and says so,
  which is what keeps an agent from looping on a question the knowledge base
  cannot answer.
* Its tools are chosen from its action, not offered as one flat list. A question
  that can be answered is never handed the workspace browser, and no turn of any
  action is handed a tool that writes canonical knowledge — writes still stop at
  proposal review, by a human.

Humans drive the state machine. `advance_turn` records one step at a time, so
the caller (an agent or a person) supplies the observation and this layer owns
the legality of the transition. Cancellation is cooperative: `stop_turn` is
idempotent and terminal, so a racing caller cannot resurrect a stopped turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import ReadScope, WorkspaceAccess, audit_access
from .harness import BrainEvent, ProactivitySetting, Turn, TurnStep
from .models import new_id
from .triage import (
    MODES,
    ProactivityPolicy,
    TriageDecision,
    classify_event,
    decide_event,
)


class TurnConflict(Exception):
    """The turn is in a state that forbids the requested transition."""


class TurnNotFound(Exception):
    """No such turn in this workspace, or none the caller may see."""


# Steps, not wall-clock. A budget in seconds measures the wrong thing: the
# failure it guards against is an agent going in circles, and each circle costs
# exactly one step.
ACTION_BUDGET: dict[str, int] = {"answer": 2, "investigate": 6, "pass": 0}

# Progressive disclosure. The action decides which tools exist for the turn, and
# the write path is absent from every set: approving a proposal is a human
# decision, so a turn cannot reach the tool that makes it.
ACTIVE_TOOLS: dict[str, tuple[str, ...]] = {
    "answer": ("search_knowledge",),
    "investigate": ("search_knowledge", "list_sources", "get_proposal"),
    "pass": (),
}
WRITE_TOOLS = ("approve_proposal", "reject_proposal", "supersede_knowledge")

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "superseded"})
OPEN_STATUSES = ("pending", "running", "awaiting_approval")

# Only real work spends budget. Triage, policy, steer, suspend and stop are
# bookkeeping, and charging the turn for them would make the number mean
# nothing.
COUNTED_KINDS = frozenset({"tool"})


@dataclass(frozen=True)
class EventOutcome:
    event: BrainEvent
    turn: Turn
    decision: TriageDecision
    superseded: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepOutcome:
    turn: Turn
    step: TurnStep
    exhausted: bool = False


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def active_tools(action: str) -> tuple[str, ...]:
    return ACTIVE_TOOLS.get(action, ())


def step_budget(action: str) -> int:
    return ACTION_BUDGET.get(action, 0)


def turn_plan(turn: Turn) -> list[str]:
    """The tools this turn may use, in the order it should try them.

    A plan, not a schedule: the caller may stop early, and the budget is what
    stops it from running long.
    """
    return list(active_tools(turn.action))


def _append_step(
    db: Session, turn: Turn, *, tool: str, kind: str, summary: str
) -> TurnStep:
    step = TurnStep(
        id=new_id("tst"),
        turn_id=turn.id,
        ordinal=turn.steps_used + 1 if kind in COUNTED_KINDS else 0,
        tool=tool,
        kind=kind,
        summary=summary[:1000],
    )
    if kind in COUNTED_KINDS:
        turn.steps_used += 1
    db.add(step)
    db.flush()
    return step


def load_turn(db: Session, access: WorkspaceAccess, turn_id: str) -> Turn:
    """Load a turn from the caller's workspace only.

    A turn in another workspace is reported as missing rather than forbidden, so
    the error cannot be used to discover that it exists.
    """
    turn = db.get(Turn, turn_id)
    if turn is None or turn.workspace_id != access.workspace_id:
        raise TurnNotFound(turn_id)
    return turn


def turn_steps(db: Session, turn: Turn) -> list[TurnStep]:
    return list(
        db.scalars(
            select(TurnStep)
            .where(TurnStep.turn_id == turn.id)
            .order_by(TurnStep.created_at, TurnStep.id)
        ).all()
    )


def policy_row(db: Session, access: WorkspaceAccess, channel: str) -> ProactivitySetting | None:
    return db.scalar(
        select(ProactivitySetting).where(
            ProactivitySetting.workspace_id == access.workspace_id,
            ProactivitySetting.channel == channel,
        )
    )


def policy_for(db: Session, access: WorkspaceAccess, channel: str) -> ProactivityPolicy:
    """The policy in force for a channel, falling back to the quiet default.

    An unset channel behaves like `mentions`: the Brain answers when named and
    stays out of the way otherwise. Defaulting to proactive would make an
    unconfigured deployment noisy, which is the one failure users cannot undo.
    """
    row = policy_row(db, access, channel)
    if row is None:
        return ProactivityPolicy()
    return ProactivityPolicy(
        mode=row.mode,
        min_confidence=row.min_confidence,
        answer_threshold=row.answer_threshold,
        allow_investigate=row.allow_investigate,
        react=row.react,
    )


def list_policies(db: Session, access: WorkspaceAccess) -> list[ProactivitySetting]:
    return list(
        db.scalars(
            select(ProactivitySetting)
            .where(ProactivitySetting.workspace_id == access.workspace_id)
            .order_by(ProactivitySetting.channel)
        ).all()
    )


def set_policy(
    db: Session,
    access: WorkspaceAccess,
    *,
    channel: str,
    mode: str | None = None,
    min_confidence: float | None = None,
    answer_threshold: float | None = None,
    allow_investigate: bool | None = None,
    react: bool | None = None,
) -> ProactivitySetting:
    """Create or update one channel's policy.

    Only the fields passed are changed, so a caller can quiet a channel without
    restating every threshold and accidentally resetting one.
    """
    if mode is not None and mode not in MODES:
        raise ValueError(f"Unknown proactivity mode: {mode}")
    for name, value in (
        ("min_confidence", min_confidence),
        ("answer_threshold", answer_threshold),
    ):
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
    row = policy_row(db, access, channel)
    if row is None:
        # Column defaults are applied by the database at INSERT time, which is
        # too late for the audit line below to read them, so an explicit default
        # is set here from the same object the reader uses.
        base = ProactivityPolicy()
        row = ProactivitySetting(
            id=new_id("prc"),
            workspace_id=access.workspace_id,
            channel=channel,
            mode=base.mode,
            min_confidence=base.min_confidence,
            answer_threshold=base.answer_threshold,
            allow_investigate=base.allow_investigate,
            react=base.react,
        )
        db.add(row)
    if mode is not None:
        row.mode = mode
    if min_confidence is not None:
        row.min_confidence = min_confidence
    if answer_threshold is not None:
        row.answer_threshold = answer_threshold
    if allow_investigate is not None:
        row.allow_investigate = allow_investigate
    if react is not None:
        row.react = react
    audit_access(
        db,
        access,
        "proactivity.updated",
        f"{channel}: mode={row.mode} floor={row.min_confidence:.2f} "
        f"answer>={row.answer_threshold:.2f}",
    )
    db.commit()
    db.refresh(row)
    return row


def supersede_open_turns(
    db: Session, access: WorkspaceAccess, *, channel: str, by_event_id: str
) -> tuple[str, ...]:
    """Close every open turn on a channel, because a newer message arrived.

    The newest message wins. Without this, two answers land on the same channel
    a minute apart and the second one reads as a correction of the first.
    """
    open_rows = list(
        db.scalars(
            select(Turn).where(
                Turn.workspace_id == access.workspace_id,
                Turn.channel == channel,
                Turn.status.in_(OPEN_STATUSES),
                Turn.event_id != by_event_id,
            )
        ).all()
    )
    for turn in open_rows:
        turn.status = "superseded"
        turn.superseded_by = by_event_id
        turn.stop_reason = "superseded"
        _append_step(
            db,
            turn,
            tool="",
            kind="supersede",
            summary="A newer message on this channel overtook this turn.",
        )
    if open_rows:
        db.flush()
    return tuple(turn.id for turn in open_rows)


def handle_event(
    db: Session,
    access: WorkspaceAccess,
    *,
    channel: str,
    text: str,
    author: str = "",
    addressed: bool = False,
    is_bot: bool = False,
    external_id: str = "",
    raw_output: str | None = None,
    evidence_strength: float = 0.0,
) -> EventOutcome:
    """Record an event, decide its action, and open the turn it deserves.

    A `pass` is recorded as a completed turn with no budget rather than as
    nothing at all: the decision to stay quiet is the part users ask about, and
    it is only answerable if it was written down.
    """
    policy = policy_for(db, access, channel)
    kind = classify_event(text=text, channel=channel, addressed=addressed, is_bot=is_bot)
    decision = decide_event(
        kind=kind,
        text=text,
        policy=policy,
        raw_output=raw_output,
        evidence_strength=evidence_strength,
    )
    event = BrainEvent(
        id=new_id("bev"),
        workspace_id=access.workspace_id,
        channel=channel,
        kind=kind,
        author=author[:120],
        text=text,
        external_id=external_id[:120],
    )
    db.add(event)
    db.flush()

    superseded: tuple[str, ...] = ()
    if decision.action != "pass" and kind in ("mention", "direct_message"):
        superseded = supersede_open_turns(db, access, channel=channel, by_event_id=event.id)

    turn = Turn(
        id=new_id("trn"),
        workspace_id=access.workspace_id,
        event_id=event.id,
        channel=channel,
        action=decision.action,
        status="pending" if decision.action != "pass" else "completed",
        confidence=decision.confidence,
        reason=decision.reason,
        step_budget=step_budget(decision.action),
        steps_used=0,
        stop_reason="" if decision.action != "pass" else "passed",
    )
    db.add(turn)
    db.flush()
    _append_step(db, turn, tool="triage", kind="triage", summary=decision.reason)
    _append_step(
        db,
        turn,
        tool="policy",
        kind="policy",
        summary=(
            f"mode={policy.mode} floor={policy.min_confidence:.2f} "
            f"answer>={policy.answer_threshold:.2f} source={decision.source}"
        ),
    )
    audit_access(
        db, access, "event.triaged", f"{channel}: {decision.action} ({decision.source})"
    )
    db.commit()
    db.refresh(event)
    db.refresh(turn)
    return EventOutcome(event=event, turn=turn, decision=decision, superseded=superseded)


def advance_turn(
    db: Session,
    access: WorkspaceAccess,
    turn: Turn,
    *,
    tool: str,
    summary: str,
) -> StepOutcome:
    """Record one executed step, enforcing the budget and the tool set.

    Exhaustion is not an error: the turn stops cleanly with a reason, which is
    more useful than an exception that hides how far it got.
    """
    if is_terminal(turn.status):
        raise TurnConflict(f"This turn is already {turn.status}")
    if turn.status == "awaiting_approval":
        raise TurnConflict("This turn is waiting on an approval decision")
    if turn.steps_used >= turn.step_budget:
        turn.status = "completed"
        turn.stop_reason = "budget_exhausted"
        step = _append_step(
            db,
            turn,
            tool="",
            kind="stop",
            summary="Step budget exhausted; stopping rather than looping.",
        )
        db.commit()
        db.refresh(turn)
        db.refresh(step)
        return StepOutcome(turn=turn, step=step, exhausted=True)
    if tool in WRITE_TOOLS:
        raise TurnConflict(
            "Writing canonical knowledge is a human decision and is not available to a turn"
        )
    if tool not in active_tools(turn.action):
        raise TurnConflict(f"Tool '{tool}' is not available to a {turn.action} turn")

    step = _append_step(db, turn, tool=tool, kind="tool", summary=summary)
    turn.status = "running"
    if turn.steps_used >= turn.step_budget:
        turn.status = "completed"
        turn.stop_reason = "budget_exhausted"
    db.commit()
    db.refresh(turn)
    db.refresh(step)
    return StepOutcome(turn=turn, step=step, exhausted=turn.stop_reason == "budget_exhausted")


def checkpoint(db: Session, turn: Turn, state: dict) -> Turn:
    """Persist what a suspended turn will need when it resumes."""
    turn.checkpoint = json.dumps(state, sort_keys=True)[:4000]
    db.commit()
    db.refresh(turn)
    return turn


def suspend_turn(
    db: Session, access: WorkspaceAccess, turn: Turn, *, proposal_id: str, question: str
) -> Turn:
    """Pause a turn at the approval gate.

    The gate is the reason this harness is safe to run unattended, so suspension
    records the proposal under review and the question the human is answering —
    a resume call has to name the decision, not just consent to continue.
    """
    if turn.status not in ("pending", "running"):
        raise TurnConflict(f"Only a pending or running turn can be suspended, not {turn.status}")
    turn.status = "awaiting_approval"
    turn.suspension = json.dumps(
        {"proposal_id": proposal_id, "question": question[:600]}, sort_keys=True
    )[:2000]
    _append_step(
        db, turn, tool="approve_proposal", kind="suspend", summary=question[:600]
    )
    audit_access(db, access, "turn.suspended", f"{turn.id}: awaiting approval")
    db.commit()
    db.refresh(turn)
    return turn


def resume_turn(
    db: Session, access: WorkspaceAccess, turn: Turn, *, approved: bool, note: str = ""
) -> Turn:
    """Resolve the approval gate and finish the turn.

    Rejection is a terminal outcome, not a retry: a declined proposal stays
    declined, and the turn says so instead of re-entering the queue it just left.
    """
    if turn.status != "awaiting_approval":
        raise TurnConflict(f"This turn is not awaiting approval (it is {turn.status})")
    if not access.can_administer:
        raise TurnConflict("Only an owner or admin may resolve an approval gate")
    if approved:
        turn.status = "completed"
        turn.stop_reason = "approved"
        summary = f"Approved by {access.principal}. {note}".strip()
    else:
        turn.status = "cancelled"
        turn.stop_reason = "approval_rejected"
        summary = f"Rejected by {access.principal}. {note}".strip()
    _append_step(db, turn, tool="approve_proposal", kind="resume", summary=summary[:600])
    audit_access(db, access, "turn.resumed", f"{turn.id}: approved={approved}")
    db.commit()
    db.refresh(turn)
    return turn


def steer_turn(db: Session, access: WorkspaceAccess, turn: Turn, *, note: str) -> Turn:
    """Add an instruction to a turn that has not finished.

    Steering appends instead of replacing, so the operator can see what the turn
    was told first and what it was told later.
    """
    if is_terminal(turn.status):
        raise TurnConflict(f"A {turn.status} turn cannot be steered")
    turn.instructions = (turn.instructions + "\n" if turn.instructions else "") + note
    _append_step(db, turn, tool="", kind="steer", summary=note[:600])
    audit_access(db, access, "turn.steered", f"{turn.id}: {note[:120]}")
    db.commit()
    db.refresh(turn)
    return turn


def stop_turn(
    db: Session, access: WorkspaceAccess, turn: Turn, *, reason: str = ""
) -> Turn:
    """Cancel a turn. Idempotent, because cancellation races by nature.

    Calling this twice is not an error and does not add a second stop step, so a
    user pressing stop while the budget check is already stopping the turn gets
    one outcome rather than a confusing failure.
    """
    if is_terminal(turn.status):
        return turn
    turn.status = "cancelled"
    turn.stop_reason = reason[:40] or "stopped_by_user"
    _append_step(db, turn, tool="", kind="stop", summary=reason[:600] or "Stopped by a person.")
    audit_access(db, access, "turn.stopped", f"{turn.id}: {turn.stop_reason}")
    db.commit()
    db.refresh(turn)
    return turn


def list_turns(
    db: Session,
    scope: ReadScope,
    *,
    status_filter: str | None = None,
    channel: str | None = None,
    limit: int = 50,
) -> list[Turn]:
    stmt = select(Turn)
    if status_filter:
        stmt = stmt.where(Turn.status == status_filter)
    if channel:
        stmt = stmt.where(Turn.channel == channel)
    stmt = stmt.order_by(Turn.created_at.desc()).limit(max(1, min(limit, 200)))
    return list(db.scalars(scope.apply(stmt, Turn)).all())
