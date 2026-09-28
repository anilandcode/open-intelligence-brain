"""Turn lifecycle at the service layer.

Every test here pins a rule that keeps the harness from becoming an unattended
writer: the budget ends a turn cleanly, write tools are unreachable from inside
a turn, a declined approval is terminal, and stopping is idempotent so two
racing cancels produce one outcome.
"""

import pytest
from sqlalchemy.orm import Session

from brain import turns as harness
from brain.access import ReadScope, WorkspaceAccess, ensure_default_workspace
from brain.database import engine
from brain.models import Workspace

QUESTION = "@brain what did we decide about enterprise pricing?"


def _access(db: Session, *, principal: str = "owner", role: str = "owner"):
    return WorkspaceAccess(workspace=ensure_default_workspace(db), principal=principal, role=role)


def _ask(db: Session, access: WorkspaceAccess, **kwargs):
    payload = {"channel": "#eng", "text": QUESTION, "addressed": True}
    payload.update(kwargs)
    return harness.handle_event(db, access, **payload)


def test_an_ambient_message_is_recorded_as_a_completed_pass():
    with Session(engine) as db:
        access = _access(db)
        outcome = _ask(db, access, text="The deploy finished at noon.", addressed=False)
        assert outcome.event.kind == "context_only"
        assert outcome.decision.action == "pass"
        # Staying quiet is a decision, so it is written down like any other.
        assert outcome.turn.status == "completed"
        assert outcome.turn.stop_reason == "passed"
        assert outcome.turn.step_budget == 0
        assert [step.kind for step in harness.turn_steps(db, outcome.turn)] == ["triage", "policy"]


def test_a_mention_opens_an_investigation_with_a_budget():
    with Session(engine) as db:
        access = _access(db)
        outcome = _ask(db, access)
        assert outcome.event.kind == "mention"
        assert outcome.decision.action == "investigate"
        assert outcome.turn.status == "pending"
        assert outcome.turn.step_budget == 6
        # Bookkeeping steps exist but are not charged to the budget, otherwise
        # the number would stop describing how much work the turn actually did.
        assert all(step.ordinal == 0 for step in harness.turn_steps(db, outcome.turn))
        assert harness.turn_plan(outcome.turn) == [
            "search_knowledge",
            "list_sources",
            "get_proposal",
        ]


def test_the_budget_ends_the_turn_instead_of_looping():
    with Session(engine) as db:
        access = _access(db)
        turn = _ask(db, access).turn
        for index in range(6):
            outcome = harness.advance_turn(
                db, access, turn, tool="search_knowledge", summary=f"looked up query {index}"
            )
        assert outcome.exhausted is True
        assert turn.status == "completed"
        assert turn.stop_reason == "budget_exhausted"
        assert turn.steps_used == 6
        # A seventh step is refused rather than silently dropped.
        with pytest.raises(harness.TurnConflict):
            harness.advance_turn(db, access, turn, tool="search_knowledge", summary="one more")


def test_a_turn_cannot_reach_the_tools_that_write_knowledge():
    with Session(engine) as db:
        access = _access(db)
        turn = _ask(db, access).turn
        with pytest.raises(harness.TurnConflict) as refused:
            harness.advance_turn(db, access, turn, tool="approve_proposal", summary="approve it")
        assert "human decision" in str(refused.value)


def test_a_tool_outside_the_plan_is_refused():
    with Session(engine) as db:
        access = _access(db)
        answerable = _ask(db, access, raw_output="ANSWER conf=0.95", evidence_strength=0.9).turn
        assert answerable.action == "answer"
        with pytest.raises(harness.TurnConflict):
            harness.advance_turn(db, access, answerable, tool="list_sources", summary="browse it")


def test_suspend_then_approve_finishes_the_turn():
    with Session(engine) as db:
        access = _access(db)
        turn = _ask(db, access).turn
        harness.suspend_turn(db, access, turn, proposal_id="prop_1", question="Approve this fact?")
        assert turn.status == "awaiting_approval"
        assert "prop_1" in turn.suspension

        # No work happens behind the gate: the turn cannot step while suspended.
        with pytest.raises(harness.TurnConflict):
            harness.advance_turn(db, access, turn, tool="search_knowledge", summary="sneak")

        resolved = harness.resume_turn(db, access, turn, approved=True, note="looks right")
        assert resolved.status == "completed"
        assert resolved.stop_reason == "approved"
        assert harness.turn_steps(db, resolved)[-1].kind == "resume"
        with pytest.raises(harness.TurnConflict):
            harness.resume_turn(db, access, turn, approved=True)


def test_a_declined_approval_is_terminal():
    with Session(engine) as db:
        access = _access(db)
        turn = _ask(db, access).turn
        harness.suspend_turn(db, access, turn, proposal_id="prop_2", question="Approve this fact?")
        declined = harness.resume_turn(db, access, turn, approved=False, note="not accurate")
        assert declined.status == "cancelled"
        assert declined.stop_reason == "approval_rejected"
        with pytest.raises(harness.TurnConflict):
            harness.advance_turn(db, access, turn, tool="search_knowledge", summary="continue anyway")


def test_only_an_admin_resolves_the_gate():
    with Session(engine) as db:
        access = _access(db)
        turn = _ask(db, access).turn
        harness.suspend_turn(db, access, turn, proposal_id="prop_3", question="Approve this fact?")
        member = _access(db, principal="member-token", role="member")
        with pytest.raises(harness.TurnConflict) as refused:
            harness.resume_turn(db, member, turn, approved=True)
        assert "owner or admin" in str(refused.value)
        assert turn.status == "awaiting_approval"


def test_stopping_is_idempotent():
    with Session(engine) as db:
        access = _access(db)
        turn = _ask(db, access).turn
        harness.stop_turn(db, access, turn, reason="operator stopped it")
        assert turn.status == "cancelled"
        assert turn.stop_reason == "operator stopped it"
        harness.stop_turn(db, access, turn)
        stops = [step for step in harness.turn_steps(db, turn) if step.kind == "stop"]
        assert len(stops) == 1


def test_steering_appends_and_is_refused_once_the_turn_ended():
    with Session(engine) as db:
        access = _access(db)
        turn = _ask(db, access).turn
        harness.steer_turn(db, access, turn, note="check the CFO's note from March")
        harness.steer_turn(db, access, turn, note="and the renewal terms")
        assert turn.instructions.splitlines() == [
            "check the CFO's note from March",
            "and the renewal terms",
        ]
        harness.stop_turn(db, access, turn)
        with pytest.raises(harness.TurnConflict):
            harness.steer_turn(db, access, turn, note="too late")


def test_a_newer_mention_supersedes_the_open_turn():
    with Session(engine) as db:
        access = _access(db)
        first = _ask(db, access, text="@brain what did we decide about pricing?")
        second = _ask(db, access, text="@brain actually, what about renewal terms?")
        assert first.turn.superseded_by == second.event.id
        assert first.turn.status == "superseded"
        assert first.turn.stop_reason == "superseded"
        assert second.superseded == (first.turn.id,)
        assert second.turn.status == "pending"
        # A second question in another channel leaves the first one alone.
        elsewhere = _ask(db, access, channel="#sales", text="@brain what about the pipeline?")
        assert elsewhere.superseded == ()


def test_a_channel_can_be_turned_all_the_way_down():
    with Session(engine) as db:
        access = _access(db)
        harness.set_policy(db, access, channel="#quiet", mode="off")
        outcome = _ask(db, access, channel="#quiet")
        assert outcome.decision.action == "pass"
        assert outcome.decision.source == "policy"
        assert outcome.turn.status == "completed"
        assert harness.policy_for(db, access, "#quiet").mode == "off"
        # The message is still recorded: silencing a channel must not blind it.
        assert outcome.event.kind == "mention"
        with pytest.raises(ValueError):
            harness.set_policy(db, access, channel="#quiet", mode="loud")


def test_turns_are_invisible_across_workspaces():
    with Session(engine) as db:
        access = _access(db)
        db.add(Workspace(id="ws_other_probe", slug="other-probe", name="Other"))
        db.commit()
        other = WorkspaceAccess(
            workspace=db.get(Workspace, "ws_other_probe"),
            principal="other-token",
            role="owner",
        )
        _ask(db, access)
        _ask(db, other)
        mine = harness.list_turns(db, ReadScope.of(access))
        theirs = harness.list_turns(db, ReadScope.of(other))
        assert len(mine) == 1 and len(theirs) == 1
        assert mine[0].workspace_id != theirs[0].workspace_id
        with pytest.raises(harness.TurnNotFound):
            harness.load_turn(db, other, mine[0].id)
