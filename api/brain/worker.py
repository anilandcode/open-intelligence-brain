"""Background worker for durable turn processing.

The harness layer owns turn state as rows. This worker picks up pending turns
and advances them automatically — searching knowledge, recording steps, and
completing or suspending as needed.

The worker is deliberately simple:
- One process, one database connection, poll every N seconds.
- Each turn gets a lease so two workers don't double-process.
- Steps are recorded before the next one is attempted, so a crash leaves an
  accurate partial transcript.
- The worker never approves proposals — that gate stays human-only.

Run with: python -m brain.worker
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import ReadScope
from .database import SessionLocal
from .harness import Turn, TurnStep
from .models import new_id
from .services import search_knowledge
from .turns import (
    advance_turn,
    is_terminal,
    turn_plan,
)

logger = logging.getLogger("brain.worker")

# Polling interval in seconds. The worker sleeps this long between sweeps.
POLL_INTERVAL = 5

# Lease duration in seconds. A turn locked longer than this is considered
# abandoned and can be reclaimed by the next sweep.
LEASE_DURATION = 300  # 5 minutes


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _claim_pending_turns(db: Session, worker_id: str) -> list[Turn]:
    """Find and lease pending turns that are not already claimed."""
    now = _now_utc()
    # Find turns that are pending and either unleased or lease-expired
    turns = list(
        db.scalars(
            select(Turn).where(
                Turn.status == "pending",
                (Turn.leased_by.is_(None)) | (Turn.lease_expires_at < now),
            ).order_by(Turn.created_at).limit(10)
        ).all()
    )
    for turn in turns:
        turn.leased_by = worker_id
        turn.lease_expires_at = datetime.fromtimestamp(
            now.timestamp() + LEASE_DURATION, tz=UTC
        )
    if turns:
        db.flush()
    return turns


def _release_lease(db: Session, turn: Turn) -> None:
    """Release a turn's lease after processing."""
    turn.leased_by = None
    turn.lease_expires_at = None
    db.flush()


def _process_turn(db: Session, turn: Turn, worker_id: str) -> None:
    """Advance a single turn through its plan.

    The worker executes each tool in the turn's plan, searching knowledge
    and recording the result as a step. If the tool finds something, the
    step records it; if not, the step records the abstention.

    The worker never writes canonical knowledge — that stays human-only.
    """
    plan = turn_plan(turn)
    if not plan:
        turn.status = "completed"
        turn.stop_reason = "no_tools"
        _release_lease(db, turn)
        db.commit()
        return

    # Execute the plan step by step
    for tool_name in plan:
        if is_terminal(turn.status):
            break

        # Check budget
        if turn.steps_used >= turn.step_budget:
            turn.status = "completed"
            turn.stop_reason = "budget_exhausted"
            step = TurnStep(
                id=new_id("tst"),
                turn_id=turn.id,
                ordinal=0,
                tool="",
                kind="stop",
                summary="Step budget exhausted; stopping rather than looping.",
            )
            db.add(step)
            db.flush()
            break

        # Execute the tool
        summary = _execute_tool(db, turn, tool_name)
        try:
            outcome = advance_turn(db, _fake_access(turn), turn, tool=tool_name, summary=summary)
            if outcome.exhausted:
                logger.info("Turn %s exhausted budget", turn.id)
                break
        except Exception as exc:
            logger.warning("Turn %s step failed: %s", turn.id, exc)
            turn.status = "failed"
            turn.stop_reason = "step_error"
            step = TurnStep(
                id=new_id("tst"),
                turn_id=turn.id,
                ordinal=0,
                tool=tool_name,
                kind="error",
                summary=f"Step failed: {exc}"[:600],
            )
            db.add(step)
            db.flush()
            break

    # If still running after all plan steps, complete it
    if not is_terminal(turn.status):
        turn.status = "completed"
        turn.stop_reason = "plan_complete"

    _release_lease(db, turn)
    db.commit()


def _execute_tool(db: Session, turn: Turn, tool_name: str) -> str:
    """Execute a single tool and return a summary string.

    The worker only has access to read tools — write tools are blocked
    at the harness level.
    """
    if tool_name == "search_knowledge":
        results = search_knowledge(db, _fake_scope(turn), turn.instructions or "general query")
        if results:
            # search_knowledge returns Knowledge ORM objects, NOT tuples —
            # index them by attribute. (top[0]/top[4] raised TypeError and
            # failed every turn that actually matched something.)
            top = results[0]
            return f"Found {len(results)} results. Top: {top.statement[:120]} (v{top.version})"
        return "No matching knowledge found."
    elif tool_name == "list_sources":
        from .models import Source
        sources = list(db.scalars(select(Source).where(
            Source.workspace_id == turn.workspace_id
        ).limit(5)).all())
        return f"Found {len(sources)} sources."
    elif tool_name == "get_proposal":
        from .models import Proposal
        # The proposal vocabulary is "proposed"/"approved"/"rejected" —
        # filtering on "pending" matched nothing and the worker always
        # reported 0 pending proposals.
        proposals = list(db.scalars(select(Proposal).where(
            Proposal.workspace_id == turn.workspace_id,
            Proposal.status == "proposed",
        ).limit(5)).all())
        return f"Found {len(proposals)} pending proposals."
    else:
        return f"Unknown tool: {tool_name}"


class _fake_access:
    """Minimal access object for worker-processed turns."""
    def __init__(self, turn: Turn):
        self.workspace_id = turn.workspace_id
        self.principal = "worker"
        self.role = "admin"
        self.can_administer = True
        self.sensitivity_ceiling = "private"


def _fake_scope(turn: Turn) -> ReadScope:
    """The worker's read scope: a real ReadScope with admin role.

    Duck-typing a scope that filtered only by workspace_id let worker
    queries skip the sensitivity ceiling that every API read enforces.
    The worker runs as admin within the turn's own workspace — the same
    reach an admin token has — so build the real thing.
    """
    return ReadScope(turn.workspace_id, "admin")


class Worker:
    """Background worker that processes pending turns."""

    def __init__(self, worker_id: str | None = None):
        self.worker_id = worker_id or f"worker-{int(time.time())}"
        self.running = True
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down…", signum)
        self.running = False

    def run(self) -> None:
        """Main worker loop."""
        logger.info("Worker %s starting (poll=%ds, lease=%ds)",
                     self.worker_id, POLL_INTERVAL, LEASE_DURATION)

        while self.running:
            try:
                self._sweep()
            except Exception as exc:
                logger.error("Sweep failed: %s", exc, exc_info=True)
            time.sleep(POLL_INTERVAL)

        logger.info("Worker %s stopped", self.worker_id)

    def _sweep(self) -> None:
        """One sweep: claim pending turns, process them, release leases."""
        db = SessionLocal()
        try:
            turns = _claim_pending_turns(db, self.worker_id)
            if not turns:
                return

            logger.info("Claimed %d turn(s)", len(turns))
            for turn in turns:
                try:
                    logger.info("Processing turn %s (action=%s, budget=%d)",
                               turn.id, turn.action, turn.step_budget)
                    _process_turn(db, turn, self.worker_id)
                    logger.info("Turn %s finished: %s (%s)",
                               turn.id, turn.status, turn.stop_reason)
                except Exception as exc:
                    logger.error("Turn %s failed: %s", turn.id, exc, exc_info=True)
                    try:
                        turn.status = "failed"
                        turn.stop_reason = "worker_error"
                        _release_lease(db, turn)
                        db.commit()
                    except Exception:
                        db.rollback()
        finally:
            db.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    worker = Worker()
    worker.run()


if __name__ == "__main__":
    main()